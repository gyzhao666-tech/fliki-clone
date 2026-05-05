# ADR-002：Agent 编排框架取舍（不引入 LangChain / LangGraph）

- 状态：Accepted
- 日期：2026-05-04
- 决策人：fliki-clone 团队
- 关联文档：`/DEVELOPMENT_PLAN.md` 第 13 节、`docs/adr/001-workflow-engine.md`、`canvases/ai-video-agent-workflow.canvas.tsx`

---

## 背景

ADR-001 选定「自研轻量 runner」作为工作流引擎。Phase 1 落地后社区与同事多次问到：

> 「你们这套不就是 agent 编排吗？为啥不直接用 LangChain / LangGraph / CrewAI？写自己的 runner 不重复造轮子？」

本 ADR 把决策讲清楚，避免每隔几周再被问一次；同时写明**什么时候应该重新评估**。

## 我们的「Agent」与社区流行的「Agent」是两件事

社区用 LangChain / LangGraph / CrewAI 时，「agent」往往指：

- 一个 LLM，自主决定下一步调哪个 tool
- 多轮 reasoning + acting（ReAct / Reflexion）循环
- DAG/状态在 prompt 里隐式表达，框架兜底执行

我们 pipeline 的「Agent」是**生产线工位**：

| 维度 | 流行 LLM Agent | 本项目的 Agent |
|---|---|---|
| 决策方式 | LLM 自主选下一步 | DAG 在 `pipeline_runs.graph_json` 显式声明 |
| 输入输出 | 自由文本 / 工具结果 | 强契约，落 `pipeline_steps.outputs_json` |
| 失败处理 | 让 LLM 重新 reason | 单步重跑 / 审批 / provider 故障切换 |
| 计价 / 配额 | 通常忽略 | 每次外部调用必落 `model_calls` 账本 + 月度 quota 预扣退还 |
| 人在回路 | 偶尔 input 提示 | 一等公民：`awaiting_review` 状态 + 审批 API |
| 可观测 | LangSmith trace 为主 | Postgres 表 + SSE 事件流 + canvas 视图 |
| 调度模型 | 单进程 + asyncio | Celery 队列分级（`interactive` / `media` / `default`） + 双模式 dispatcher |

我们要解决的核心问题是「**多步生产流程的可靠执行 + 计价 + 审批 + 故障切换**」，不是「**让 LLM 自己决定下一步**」。

## 候选方案

### 方案 A：LangChain（不选）

- **优点**：生态广、provider adapter 多、有现成的 prompt template / output parser
- **缺点**：
  - 套娃严重：一个简单 chat completion 要走 5+ 层 wrapper；调试时栈深 30+
  - 版本破坏性变更频繁（0.0.x → 0.1 → 0.2 → 0.3 多次重写核心 API），生产项目长期维护负担大
  - 不解决我们的核心问题（DAG / 审批 / 配额 / 故障切换都得自己加）
  - 与现有 `model_gateway`（已统一 5 provider + 自动 fallback + record_call）功能正好重叠，引入只会双层抽象

### 方案 B：LangGraph（不选，但作为 Agent 内部工具留口子）

- **优点**：
  - DAG 调度模型确实匹配我们的 pipeline 概念
  - 有 `checkpoint` 支持中断恢复
  - 比 LangChain 抽象更克制
- **缺点**：
  - 仍在快速演进；checkpoint 强绑 sqlite / postgres，与我们已经在用的 `pipeline_steps.outputs_json` 表是双写
  - Celery 队列分级（按 agent_type 跑不同 worker 池） / Redis pub/sub 事件总线 / 月度配额预扣退还，LangGraph 都没有，仍要自己接
  - 状态机要按 LangGraph 的方式表达，前端 SSE 协议要重构
  - **真正的杀手锏**：把已落地的「单步重跑」「审批」「partial_failed」「cancel + 退还配额」这些已上线行为往 LangGraph 上重新搭一遍，工作量比当前 runner 从零到上线还大

### 方案 C：CrewAI / AutoGen（不选）

- 设计目标是「多 agent 协作 + 自由对话产物」，与我们「工位流水线 + 强契约 + 配额账本」错位
- 没有审批 / 取消 / 计价的一等公民支持

### 方案 D：自研轻量 runner ×（已实装，本 ADR 确认延续）

- 所有状态在 Postgres：可 join、可审计、可被 Alembic 管控
- 调度复用 Celery + Redis（运维栈无新增）
- Agent 协议简单（`Step.run(ctx) -> StepResult`），新人 1h 能写一个新 Agent
- 与 SSE 事件总线 / model_gateway / 配额闭环直接打通

## 决策

**继续 ADR-001 的方案 C：自研轻量 runner**。**不**引入 LangChain / LangGraph 作为编排层。

但**留以下口子**，不强制禁用：

1. **单 Agent 内部**可以用任何工具：某个 Agent 想用 LangChain 做 LLM client、用 LangGraph 描述自身多轮工具调用，**只要 `Step.run(ctx) -> StepResult` 协议不变**就 OK。例如未来 ReviewAgent v2 想做"看视频→提缺陷→决定是否打回"的内部多轮 reasoning，可以在 `agents/review.py` 内用 LangGraph，对外仍是一个 step。
2. **Provider 接入**继续走 `model_gateway`，禁止 Agent 直接 import LangChain `ChatOpenAI` 之类——会绕开 `record_call` 的账单 + fallback 链。

## 重新评估触发条件

满足任一条件时，开 ADR-003 评估是否引入 LangGraph 作为编排层：

1. Pipeline 模板数 > 20，且模板间有大量子流程复用（共享子 DAG）
2. 出现「LLM 在某 step 里自主决定要不要插入新 step」的需求（即真正动态 DAG）
3. 跨 run 协调需求（一个 run 等另一个 run 完成的某 step 才能继续）
4. 团队成员 > 6 人，多人并行写 agent 时社区抽象的标准化收益开始大于自研维护成本

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 自研 runner 在边缘场景缺特性（cron 调度、子 workflow） | 出现需求时单独加；不为「以后可能用到」预编码 |
| 团队招到「只会 LangChain」的同事 | 入职第一周读这份 ADR + ADR-001；Agent 协议本身极简，迁移认知成本 < 半天 |
| 社区某天出现「明显碾压」的开源框架 | 触发条件里第 4 项已包含；定期（每季度）扫一次 |
| 内部 Agent 偷偷直连 OpenAI 绕过 model_gateway | code review 红线；CI 加 grep 扫描 `from openai import` / `from langchain_openai import` 出现在 `services/pipeline/agents/` 下时报警 |

## 不做什么（同样写下来避免漂移）

- 不做「让某个 LLM 看着 graph 决定下一步派发哪个 step」——current pipeline 的下一步是 `_claim_next_ready_step` 纯查询，不上 LLM
- 不做「Agent 之间自由对话」——所有 Agent 通讯都通过 `pipeline_steps.outputs_json` 落库，禁止内存传递
- 不做「跑一个 LangGraph 当 sub-step」直到上面的触发条件命中

## 参考

- ADR-001（工作流引擎选型，本 ADR 是它的延伸）
- LangChain 0.x → 0.3 的 changelog（参考其破坏性变更密度）
- 我们已落地的关键文件：
  - `app/services/pipeline/runner.py`（runner / 状态机 / 配额结算）
  - `app/services/pipeline/types.py`（Step 协议）
  - `app/services/pipeline/templates.py`（模板 = 显式 DAG）
  - `app/services/model_gateway/`（统一 provider / 计价 / fallback）
