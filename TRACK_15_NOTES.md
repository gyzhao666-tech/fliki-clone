# Track-15 · DLQ retry 识别 publish.execute_plan task

> 分支：`track-15-dlq-retry-publish`
> Worktree：`/Users/zhaoguangyuan/project/empty-track15`
> 基线：`68fccd3 docs(agents): 第三波 Backlog（Track-13/14/15/16/17 完整卡片 + T-18/19 待派）`
> 目标：让 DLQ 重投按 `task_name` 路由；publish 死信走 `execute_publish_plan_task` /
>       `_publish_execute_with_events`，而不是被错误丢进 `tick_task`。

## 1. 背景 / 为什么改

Track-03 把 `POST /publish-plans/{id}/execute` 异步化后，publish 任务体走的是
`_publish_execute_with_events`（celery 模式：`execute_publish_plan_task`；BG 模式：
直接 `BackgroundTasks.add_task` 同一函数）。系统级异常（`PublishError` / 未捕获）
进 DLQ 时，`pipeline_dlq.push(task_name="publish.execute_plan", args=[plan_id],
kwargs={"user_id": ...}, user_id=...)` —— **没有 run_id**（publish_plans 与
pipeline_runs 没有外键关联）。

旧版 `_retry_dispatch(run_id, bg)` 只接 `run_id`，且固定派 `tick_task`：
1. 在 `routers/dlq.py::retry_dlq` 入口先被 `if not run_id: raise 400` 拒掉，用户
   永远点不动这种 DLQ 项（已 retried 的不能再 retry → DLQ panel 死锁）。
2. 即使 router 不拦，`tick_task.delay(run_id=plan_id)` 也是「调度一个不存在的
   pipeline run」→ `_claim_next_ready_step` 返 None → `_settle_run_state`，发布
   行为零，DLQ 行被静默标 retried 误导审计。

修复：把派发表按 `task_name` 分支化（与 Track-03 task 注册矩阵对齐）。

## 2. 改动文件

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone-api/app/routers/dlq.py` | `_retry_dispatch(run_id, bg)` → `_retry_dispatch(dead, bg)`：按 `dead.task_name` 路由（`publish.execute_plan` / 其它两条 tick 路径）；`run_id` 必需性检查从 router 上移到 dispatch 内（让 publish 死信能跳过） | 单点路由表，避免每加一种 task 都要改 router；与 `_publish_execute_with_events` push 的 `args=[plan_id]`+`kwargs.user_id` 形态严格对齐 |
| `fliki-clone-api/tests/test_dlq_retry_publish.py` | 新建 7 case 覆盖 publish×celery / publish×BG / user_id fallback / 缺 plan_id / tick×celery 回归 / tick×BG 回归 / 缺 run_id 报错带 task_name | 防止后续重构再次把 publish 死信丢进 tick；BG 路径要断言 `bg.tasks[0].func is _publish_execute_with_events`（不是 tick） |

**没碰**：alembic（Track-16 占独占）、`.env`/`config.py`、`pipeline/page.tsx`、
`use-publish-plan-stream.ts`（Track-13 / Track-17 错峰段）、
`services/pipeline/tasks.py` 函数体本身、`services/publishing/`。

## 3. 路由分发矩阵（修复后）

| `task_name` | celery_enabled=true | celery_enabled=false |
|---|---|---|
| `publish.execute_plan` | `execute_publish_plan_task.apply_async(args=[plan_id], kwargs={"user_id": user_id}, queue="default")` | `bg.add_task(_publish_execute_with_events, plan_id, user_id)` |
| `pipeline.tick` / `pipeline.execute_step` / `background.tick` | `tick_task.delay(run_id)` | `bg.add_task(runner.tick, run_id)` |

边界：
- publish 死信 args/kwargs 都缺 plan_id → HTTP 400（之前会静默 NPE）
- 非 publish 类且无 run_id → HTTP 400 携带 task_name 方便定位（旧版只有泛错）
- `kwargs.user_id` 缺时 fallback 到 `dead.user_id`（行级冗余兜底，兼容老 push 行）

## 4. 烟测结果

```
$ cd fliki-clone-api && make test
...
48 passed, 1 warning in 1.61s
```

- 41 → 48 PASS（41 基线 + 7 新增），零回归。
- 只跑新文件：`pytest tests/test_dlq_retry_publish.py -v` → 7/7 PASS, 1.15s。

新增 7 case 全部 `@pytest.mark.unit`，无 PG 依赖（无外键写库），CI runner 没装 PG
也能直接跑。

可选人工烟测（待后端重启加载新代码后做，sandbox 里跑全栈风险大）：

```bash
# 1. 让一条 publish.execute_plan 死信入库（最简单：误绑 youtube 凭证后点 Upload）
# 2. 前端 DLQ panel 看到该行 status=pending
# 3. 点 Retry 按钮
# 4. 后端日志：dispatcher=celery（或 background），不再是 "task=pipeline.tick"
# 5. redis-cli LRANGE celery 0 -1 → 应有一条 'publish.execute_plan' payload（celery 模式）
# 6. 前端 PlanRow 出现 publish_plan_state running → completed/system_error
```

## 5. 已知边界 / 跳过

- **不做** publish 死信批量 retry（单选行级，与既有 tick 类一致；批量留长尾）。
- **不做** 自动 retry 策略 / 退避（Track-03 设计上 `max_retries=0` 就是要让用户决定）。
- **不动** task body：`_publish_execute_with_events` 的 SSE phase 与 DLQ push 逻辑保持
  原样（已经在 Track-03 里反复验证过）。
- **不动** `args_json` 序列化形态：`pipeline_dlq.push` 落库时已经是 list/dict，`get()`
  读出时 psycopg2 自动反序列化；测试直接构造 dict 不走 DB，覆盖了 dispatch 纯函数语义。

## 6. Follow-up

1. **真账号 e2e**：用户在真启 backend + redis 后，触发一条 `PublishError`（如把
   YouTube refresh_token 弄失效）→ DLQ 入库 → 前端 panel 点 Retry → 看 redis
   `default` 队列是否真出现 `publish.execute_plan` payload + worker 真重新调
   adapter。本 sandbox 不真发外网，留人工。
2. **DLQ 行的 `args_json` 类型守护**：当前从 `dead.get("args_json")` 直接 `list(...)`，
   依赖 psycopg2 自动反 JSON。如果后续 DLQ service 把列改成 JSONB string 储存，
   或 SQL 路径变更，需要在 dispatch 前主动 `json.loads`。已在测试里以 list/dict 形态
   断言，避免重构时悄悄破坏。
3. **router 路径头部那条 stale 注释**（`# 注意：从 pipelines 路由复用 _schedule_tick 会引入循环 import`）
   仍指向 `get_settings` import，但现在 dispatch 已内嵌；下次重构可以挪到 `_retry_dispatch`
   docstring 里。本次为最小改动没动。
4. **统一 publish task 与 pipeline task 的 DLQ 关联**：当前 publish 死信只有 user_id
   没有 file_id / plan 状态快照，前端 panel 难按文件聚合。建议下一波（或 L 列）给
   `dead_letter_tasks` 加 `meta_json`（落 plan/file_id），与 Track-13 进度回写解耦。

## 7. 协调者合并 checklist 提醒

- 没动 alembic、`.env`、`config.py`、前端文件、`tasks.py`：互斥锁全部遵守。
- 没 push、没切回 main、没改 `SESSION_HANDOFF.md`。
- 单 commit 在 `track-15-dlq-retry-publish` feature branch。
- 验收：`cd fliki-clone-api && make test` 应得 48 PASS（41 基线 + 7 新）。
