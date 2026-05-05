# ADR-001：工作流引擎选型

- 状态：Accepted
- 日期：2026-05-04
- 决策人：fliki-clone 团队
- 关联文档：`/DEVELOPMENT_PLAN.md`、`canvases/ai-video-agent-workflow.canvas.tsx`

---

## 背景

当前 `fliki-clone-api` 已有：
- FastAPI + asyncpg + Alembic + Celery + Redis
- `routers/scenes.py` 实装了可灵 / 硅基流动 / 演示三层降级的视频生成
- 进度流通过 Redis + SSE 推送
- 视频生成是“单条 BackgroundTask 串行做完整片”的形态

要演进到《DEVELOPMENT_PLAN》中描述的多 Agent 流水线，必须有一个能描述并执行 DAG 的“工作流引擎”：每个 Agent 工位是一个节点，节点之间有依赖、可单步重跑、可人工审批、可回滚、可观测。

## 候选方案

### 方案 A：Temporal
- 优点：生产级别的 workflow 引擎，长任务、重试、版本化、信号、子工作流原生支持。
- 缺点：
  - 需要单独部署 Temporal Server（运维成本明显）
  - 学习曲线陡峭，团队首次接触
  - 与现有 Celery 不兼容，需要并行存在或迁移
  - 当前流量与复杂度还配不上

### 方案 B：Prefect
- 优点：Python 原生，DAG 描述直观，UI 能看任务图。
- 缺点：
  - 自托管 server 仍是负担，托管 Cloud 引入第三方依赖
  - 与 FastAPI / Celery 现有进程模型有重叠
  - 远程 worker 与现有 R2 / Redis / Postgres 集成需要适配

### 方案 C：自研 Celery + 状态表轻量 runner（**选定**）
- 思路：
  - Pipeline DAG 用 JSON 显式描述，存在 `pipeline_runs.graph_json`
  - 每个节点是一个 Celery task；调度器负责 ready → enqueue
  - 状态机：`queued / running / awaiting_review / partial_failed / succeeded / failed / cancelled`
  - 单步重跑、审批通过 API 改 `pipeline_steps` 状态再触发
- 优点：
  - 复用现有 Celery + Redis，无新基础设施
  - 与现有 BackgroundTask / SSE 模型一致
  - 学习成本低，团队可控
- 缺点：
  - 重试、退避、超时、信号、版本化要自己实现
  - 后期复杂度上升后可能要迁移到 Temporal

## 决策

**采用方案 C：自研轻量 runner**，作为 Phase 1 的工作流执行引擎。

迁移触发条件（写明，避免后期争论）：
1. Pipeline 节点平均数 > 30 / run，或 DAG 嵌套层级 > 3。
2. 同时跑的 pipeline run > 200 个，或队列堆积持续 > 5 分钟。
3. 跨多个外部模型供应商的协调（含子工作流）超过 3 处需求。

满足任一条件时，启动 ADR-002 评审是否切换到 Temporal。

## 详细设计

### 数据模型（Phase 1 新增）

- `pipeline_runs`
  - `id`, `file_id`, `user_id`, `template_name`, `graph_json`, `state`, `current_cursor`, `cost_estimated_usd`, `cost_actual_usd`, `created_at`, `updated_at`, `finished_at`
- `pipeline_steps`
  - `id`, `run_id`, `name`, `agent_type`, `depends_on_json`, `state`, `attempt`, `inputs_json`, `outputs_json`, `error`, `started_at`, `finished_at`
- `model_calls`（独立于 pipeline，保留所有外部模型调用账单；Phase 1 先落库）
  - `id`, `user_id`, `file_id`, `pipeline_step_id`, `provider`, `model`, `action`, `cost_usd`, `duration_ms`, `status`, `error`, `created_at`

### 节点协议

```python
class Step(Protocol):
    name: str
    agent_type: str  # research / script / art / video / voice / edit / review / publish
    depends_on: list[str]
    retry_policy: RetryPolicy
    idempotency_key: str

    def run(self, ctx: PipelineContext) -> StepResult: ...
```

### 状态机

```
queued → running → succeeded
running → awaiting_review → succeeded   （人工审批通过）
running → partial_failed → running      （单步重跑）
running → failed                        （重试耗尽）
任意 → cancelled                        （用户/系统取消）
```

### 调度器

- 单 Celery beat 任务（`pipeline.tick`）周期性扫描 `running` 的 run，把 `queued` 且依赖完成的 step 派发到对应队列：
  - `agents.research`、`agents.script`、`agents.art`、`agents.video`、`agents.voice`、`agents.edit`、`agents.review`、`agents.publish`
- 每个队列独立 worker 池，便于按模型供应商配并发上限。

### 失败与重试

- 节点级 `retry_policy`：最大次数、指数退避、抖动。
- 重试耗尽后：
  - `agent_type ∈ {video, voice}` 默认进入 `partial_failed`，等待人工或自动降级（切换 provider 重跑）
  - 其他类型默认 `failed`，整个 run 进入 `partial_failed` 等待人工

### 接口

- `POST /api/pipelines`：基于 file_id + template 启动一个 run
- `GET  /api/pipelines/{id}`：查询 run + steps 状态与产物
- `POST /api/pipelines/{id}/cancel`
- `POST /api/pipelines/{id}/steps/{name}/rerun`
- `POST /api/pipelines/{id}/steps/{name}/approve`
- `GET  /api/pipelines/{id}/stream`：SSE 增量推送（关闭重连可从 DB 拉最新）

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 自研调度有 bug 导致死锁 | 节点强制 timeout；外层 watchdog 周期性回收 stuck step |
| 依赖描述错误 | 启动时校验 DAG 是否有环 / 孤儿节点 |
| 状态机扩散 | 每次新增状态先写 ADR；前后端共享枚举常量 |
| 重试风暴 | 节点级 idempotency_key + provider 限流 |
| 切换 Temporal 时迁移成本 | 节点协议保持稳定，迁移时仅替换 runner 实现 |

## 接下来要做的事

1. 实现 `services/pipeline/runner.py` 与 `models/pipeline_run.py`、`models/pipeline_step.py`
2. 实现节点协议与最小 ResearchAgent / ScriptAgent
3. Celery beat 集成（`pipeline.tick` 定时器）
4. API 层接入并打通前端 `/app/project/[id]/pipeline`
