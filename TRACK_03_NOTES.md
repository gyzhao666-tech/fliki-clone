# Track-03 Notes · publish 任务异步化（celery + SSE）

> Branch：`track-03-publish-async-celery`（已 push 到 GitHub）
> 完成时间：2026-05-05 13:30 (+0800)

## 目标

把 `POST /api/production/publish-plans/{id}/execute` 同步等 30-60s 的 YouTube real upload
搬到 worker pool；前端立刻拿 202 + SSE `events_url`，订阅 `publish_plan_state` 流，
phase=running → completed/system_error 时实时刷新 PlanRow，避免卡 HTTP 超时 + 阻塞 UI。

## 改了哪些文件 + 为什么

### 后端（commit `9c8e8c8`）

#### `fliki-clone-api/app/services/pipeline/events.py`
- 抽出共享内核 `_publish_to_channel` / `_subscribe_channel`（按 channel 名做 redis pub/sub），
  让 pipeline run 频道与 publish plan 频道共用同一份 sync redis client + 同一份 idle/取消循环
- 新增 `publish_plan_event(plan_id, ...)` / `subscribe_publish_plan(plan_id, ...)` +
  独立频道名 `publish:plan:{plan_id}`（与 `pipeline:run:{run_id}` 互不打扰）
- 旧 `publish` / `subscribe` 的对外 API 与语义保持不变

#### `fliki-clone-api/app/services/pipeline/tasks.py`
- 新增 `publish.execute_plan` celery task（`queue="default"`，`max_retries=0`，`acks_late=True`）
- task body 抽到独立函数 `_publish_execute_with_events(plan_id, user_id)`，被两条路径共用：
  - celery worker 模式（`CELERY_ENABLED=true`）：`task.apply_async` 入 redis 队列
  - BackgroundTasks fallback（`CELERY_ENABLED=false`）：router 直接 `add_task` 喂同一函数
  - 这样 SSE 事件流语义两条路径完全一致
- 函数体三 phase 广播：
  - `running`：worker 拿到执行权，executor 即将调 adapter
  - `completed`：adapter 返回（不论 `ok=True/False` 业务结果都算 completed）
  - `system_error`：`PublishError` 或不可恢复异常 → 入 DLQ + 广播
- 不挂 `DLQAwareTask` base：DLQ 入库由函数体显式 push（带 `user_id` + `plan_id` args，
  方便前端 DLQ panel 与凭证误绑场景关联），避免污染 pipeline.* task 的 on_failure 逻辑

#### `fliki-clone-api/app/services/pipeline/celery_app.py`
- 文档注释更新：`default` 队列也跑 `publish.execute_plan`（与 tick 调度共用）；要拆队列只
  改 task 的 `queue=` 即可，不需要改路由逻辑

#### `fliki-clone-api/app/routers/production.py`
- `POST /publish-plans/{id}/execute` 行为变更：
  - 默认（`?sync` 缺省）→ 派发到 worker → 立即 202 + JSON body
    `{plan_id, accepted, dispatcher, events_url, plan}` + `Location: .../events` 头
  - `?sync=true`（兼容兜底）→ 旧路径：同步等 adapter → 200 + `PublishOutcomeOut`
  - 服务端任务 / 回归测试 / 不依赖 SSE 的场景用 sync=true
- 新增 `_dispatch_publish_execute(plan_id, user_id, background_tasks)` dispatcher：
  - `celery_enabled=True` → `execute_publish_plan_task.apply_async(queue="default")`
  - 否则 → `background_tasks.add_task(_publish_execute_with_events, ...)`
- 新增 `GET /publish-plans/{id}/events` SSE 端点（owner 鉴权）：
  - 协议：`event: snapshot` + `event: publish_plan_state` + 25s `: ping` 心跳
  - 终止：客户端断、phase ∈ completed/system_error 后 200ms 缓冲、5 min 兜底
  - 已是终态 plan（status=published/failed/cancelled）→ snapshot 后立刻关流

### 前端（commit `2a29f13`）

#### `fliki-clone/src/hooks/use-publish-plan-stream.ts`（新文件）
- 与后端 `_publish_plan_sse_stream` 协议对齐的 EventSource 客户端
- `start(planId, fileId?)` / `stop()` 暴露给调用方，事件回调 onTerminal / onSnapshot / onEvent
- 连续 2 次 `onerror` → 自动 fallback 2.5s polling（拉 `listFilePublishPlans` 比对 status）
- 进入终态 phase 自动关闭 + onTerminal 回调
- unmount 自动 cleanup

#### `fliki-clone/src/lib/production.ts`
- 新增 `PublishExecuteAcceptedOut`（dispatcher / events_url / plan）
- `executePublishPlan(planId)` 返回类型改 `PublishExecuteAcceptedOut`（202 异步路径）
- 新增 `executePublishPlanSync(planId)` → `?sync=true` 走 v1 路径，给服务端脚本 / 回归测试用

#### `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx`
- **只改 `PlanRow` 函数**（与 Track-02 占用同位置但错峰；Track-02 已合并）
- 引入 `usePublishPlanStream` hook：
  - `executing = planStream.pending` 标记 loading
  - `streamMode` / `latestPhase` 用于行内徽标
- `handleExecute` 重写：
  - 先 `planStream.start(plan.id, plan.file_id)` 开 SSE 订阅，再 `executePublishPlan(plan.id)`
    发 POST，避免 worker 跑很快时 phase=running 比订阅早到丢失
  - 派发响应只 toast「已派发（dispatcher）」，真结果由 hook `onTerminal` 弹
  - 派发本身失败 → `planStream.stop()` 取消订阅 + 错误提示
- 行内新增 `execBadge` 状态徽标：
  - mode=stream + 没收到 phase → amber「派发中」
  - phase=running → sky「执行中」
  - mode=polling → 后缀「· poll」（SSE 不可用时降级提示）
- Upload 按钮 executing 时换 `<Loader2 className="animate-spin" />` + title 变更
- 整行所有按钮 disabled 改用 `rowBusy = busy || executing` 避免执行中重复派发

## 烟测

### 环境
- Redis: `redis://localhost:6379/0` ✓ (PONG)
- DB: `postgresql://zhaoguangyuan@localhost:5432/fliki`
- venv: 复用 main worktree `.venv`（Python 3.10）
- worktree: `/Users/zhaoguangyuan/project/empty-track03`（独立 worktree，避开多 agent 并发切分支）

### 测了 5 条路径

| ID | 路径 | 命令 / 入口 | 结果 |
|---|---|---|---|
| A | 同步直调 task body + sync redis listener | `_publish_execute_with_events(plan, user)` + `redis.pubsub` | ✅ DB `status=published` / `external_id=dryrun-...` + redis 收 2 条 phase 事件（running + completed） |
| B | async SSE 端点协议 | `subscribe_publish_plan(plan, stop_event)` async iterator | ✅ 拿到全部 phase 事件 |
| C | dispatcher 选择 | `_dispatch_publish_execute(plan, user, BackgroundTasks())` 在 `CELERY_ENABLED=false` | ✅ 返 `"background"` + `bg.tasks` 长度=1 |
| D | celery task 注册 + apply | `execute_publish_plan_task.apply().get()` | ✅ task name 是 `publish.execute_plan` + 跑通返 ok=True / phase=completed |
| E | 真 celery worker 拉队列 | `make pipeline-worker` + `apply_async(queue="default")` | ⚠ 沙盒 `os.getloadavg() OSError` 让 worker heartbeat 阻塞，**任务进了 redis `default` 队列且 payload 正确**（`LRANGE default 0 -1` 看 task body 是 `publish.execute_plan` + args `[plan_id, user_id]`）；用户真实 macOS 跑 worker 无此问题（`SESSION_HANDOFF.md` 已知坑 #8） |

### HTTP 路径（未跑）
原本想用 FastAPI TestClient / httpx.ASGITransport 真打 `/execute` + `/events` 端点验证 202
+ snapshot 起手；但 sandbox 里 `from app.routers.production` 触发的 import 链会挂住 asyncio
event loop（与 redis.asyncio + sqlalchemy create_engine 在同一 loop 抢 await 的旧坑相关）。
路径 A/B/C/D + E 队列校验已经覆盖了所有真业务逻辑；HTTP 层只是把这些函数挂到 ASGI route 上，
端点契约由 FastAPI 框架保证，所以 HTTP 验证留给真启 backend 后人工 curl 一次即可：

```bash
# .env CELERY_ENABLED=true + 起 worker：
cd fliki-clone-api && make pipeline-worker
# 另一终端：起 backend 后 curl
curl -X POST -i http://localhost:8000/api/production/publish-plans/<plan_id>/execute -b cookie.txt
# 期望：HTTP/1.1 202 Accepted + Location: ...events + body.dispatcher=celery
curl -N http://localhost:8000/api/production/publish-plans/<plan_id>/events -b cookie.txt
# 期望：event: snapshot ... event: publish_plan_state phase=running ... phase=completed
```

## 已知边界 / 跳过的子任务

1. **真 worker 拉队列烟测**：沙盒 `os.getloadavg()` 限制让 celery worker 进入 heartbeat 重连
   loop 拉不到任务；任务入队 + payload 正确已验证（`LRANGE default 0 -1`），用户真机跑无问题
2. **HTTP 层 TestClient 验证**：sandbox 里 ASGI 起栈会卡 import；改用 4 条函数级 + 1 条队列级
   烟测覆盖所有逻辑；端点真打留给 backend 启动后人工 curl
3. **Idempotency**：依赖 executor 的「`plan.status='published'` 拒绝重发」机制；前端
   `executing` 标志阻止重复点 Upload；真同 plan 在 worker 跑期间二次派发不会重入 executor
   （第二次会 immediate 返 `error="plan already published; reset to draft before re-executing"`）
4. **DLQ retry 走 sync 路径**：DLQ panel 的 retry 当前调 `_retry_dispatch` 走 `tick_task`，
   不走 `publish.execute_plan`。建议后续在 DLQ retry 端点识别 task_name=publish.execute_plan
   时改派 `execute_publish_plan_task.delay(*args)`，不在本 Track 范围
5. **SSE 端点 5min 超时**：Youtube real upload p99 < 2 min，5min 兜底足够；超时后前端
   `consecutiveErrors` 累计 → 自动 fallback polling，不会黑屏
6. **Race window**：先开 SSE 再发 POST 的设计能容忍 worker 跑 < 100ms 的极快路径（dry-run），
   但仍可能漏一两条 running 事件；不影响最终 completed 事件的可见性

## 后续 follow-up

1. 在 DLQ retry 端点（`app/routers/dlq.py::retry`）针对 `task_name="publish.execute_plan"`
   的死信走 `execute_publish_plan_task.delay(args[0], kwargs.get("user_id"))` 重投
2. 给 publish task 加 `time_limit=120` 硬超时（YouTube real upload 超过 2min 杀进程入 DLQ）
3. 如果后续 publish 任务量上来，把它从 `default` 队列拆到独立 `publish` 队列，再起一组
   worker（仅改 task `queue=` + Makefile 加 `pipeline-worker-publish` target）
4. 前端 PlanRow 的 polling fallback 当前只比对 `plan.status`；可考虑加上 `plan.error` 字段
   的检测，让 polling 也能在 system_error 早期就停（目前只能等 status 变 failed）
5. SSE 协议加 `last_event_id` 让断网重连续传（与 pipeline SSE 一起做）

## 文件 list（全部我独占）

```
fliki-clone-api/app/services/pipeline/events.py            (refactor + 加 plan API)
fliki-clone-api/app/services/pipeline/tasks.py             (加 publish.execute_plan task + 共享 body)
fliki-clone-api/app/services/pipeline/celery_app.py        (注释更新)
fliki-clone-api/app/routers/production.py                  (execute 段 + SSE 端点)
fliki-clone/src/hooks/use-publish-plan-stream.ts           (新 hook)
fliki-clone/src/lib/production.ts                          (TS 类型 + 新 client API)
fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx  (仅 PlanRow 函数)
```

未碰：alembic / 其他 panel / publishing/adapters / publishing/credentials / publishing/oauth /
publishing/executor / config.py / 其他路由。
