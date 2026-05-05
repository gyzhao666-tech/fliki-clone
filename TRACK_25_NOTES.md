# Track-25 · 配额超限 / Provider 桶满 SSE 实时推送

> 分支：`track-25-quota-exceeded-sse`
> 基线：`ff48c75 docs(agents): 第五波 Backlog（T-20/21/22/23/24/25 完整卡片）`
> 测试：`make test` → **99 PASS**（89 baseline + 10 新增）
> alembic：**不动**（仍是 `c3d4e5f6a7b8`）
> .env / config.py：**不动**

## 1. 改了哪些文件 + 为什么

| 文件 | 类型 | 变更 |
|---|---|---|
| `fliki-clone-api/app/services/pipeline/events.py` | 后端 / 内核 | 在 Track-17 抽出的 `_publish_to_channel` / `_subscribe_channel` 之上**新加** `_user_channel(user_id)` / `publish_user_event(user_id, event_type, payload)` / `subscribe_user(user_id, ...)`，channel 名 `user:{user_id}`；既有 `pipeline:run:{run_id}` / `publish:plan:{plan_id}` 两条频道**完全不动**，新频道与它们独立 stream key（`user:{user_id}:stream`），互不打扰；payload envelope `{type, data}` 与既有事件一致；redis 不可用时 `_publish_to_channel` 已经 noop（warning + 跳），不需要在外层再加 try。 |
| `fliki-clone-api/app/services/pipeline/quota.py` | 后端 / 业务 | `reserve_tenant(tenant_id, amount, *, plan, display_name, user_id=None)`：新增 `user_id` kwarg；超限分支在 `return ReserveResult(ok=False, ...)` 之前 `try: events.publish_user_event(user_id, "quota_exceeded", payload)`，payload 含 `tenant_id` / `kind="monthly_quota"` / `message` / `attempted_cost` / `monthly_limit` / `current_usage`（满足卡片要求 5 字段）；`user_id` 缺省 None 时跳 publish 保证向后兼容（老脚本不被打断）；publish 抛异常仅 warning 不阻断 quota 主流程。 |
| `fliki-clone-api/app/services/pipeline/provider_buckets.py` | 后端 / 业务 | `acquire(tenant_id, provider_name, *, plan="free", user_id=None)`：新增 `user_id` kwarg；BucketFull 抛出**之前**先调 `events.publish_user_event(user_id, "bucket_full", payload)`，payload 含 `tenant_id` / `kind="provider_bucket"` / `provider_name` / `message` / `current_in_flight` / `max_concurrent`；同 quota 一致 publish 失败仅 warning。 |
| `fliki-clone-api/app/services/model_gateway/gateway.py` | 后端 / 串联 | gateway.run() 调 `provider_buckets.acquire(...)` 时透传 `user_id=request.user_id`，gateway 自带的 user_id（VoiceAgent / VideoAgent / EditAgent 都从 `RenderRequest.user_id` 进来）一路打到事件总线。 |
| `fliki-clone-api/app/routers/pipelines.py` | 后端 / API | (1) 启动 pipeline 时把 `user_id=current_user.id` 透传给 `reserve_tenant`，超限自动推 quota_exceeded；(2) 末尾**新加** `GET /api/pipelines/user-events` SSE：连接时先发 `snapshot`（quota + provider_buckets 全量，与 `/quota` + `/buckets` 字段对齐）→ 然后 `subscribe_user(current_user.id)` 长连接拉 `quota_exceeded` / `bucket_full`；30 分钟兜底 + 客户端断开 + redis 抖动均能平稳关闭；与 `/{run_id}/events` 共用 `_sse_format` / `_SSE_HEARTBEAT_SEC` / `_SSE_MAX_DURATION_SEC` 常量，不引重复代码。 |
| `fliki-clone/src/hooks/use-user-events.ts` | 前端 / hook（**新文件**）| 浏览器原生 EventSource 订阅 `/api/pipelines/user-events`：监听 `snapshot`（仅缓存 quota / 桶状态作为 toast 文案兜底）/ `quota_exceeded`（→ `feedback.error("月度额度不足，剩余 $X")`，X 优先取 payload.monthly_limit-current_usage，缺则用 snapshot.remaining_usd）/ `bucket_full`（→ `feedback.warning("Provider {name} 并发到上限，请稍后")`）；同事件 1.5s 内去重防刷屏；onerror 不主动 close（保留浏览器原生 Last-Event-ID 续传机会）。 |
| `fliki-clone/src/components/user-events-listener.tsx` | 前端 / 包装（**新文件**）| 把 `useUserEvents` 包成无渲染 client component（`"use client"` + return null）；让 `(app)/layout.tsx` 不需要切成 client 也能挂上全局监听。 |
| `fliki-clone/src/app/[locale]/(app)/layout.tsx` | 前端 / 挂载点 | 引入 `UserEventsListener` + 在 `AppShell` 内一行 `<UserEventsListener />`；layout 仍保留 `force-dynamic` server component 语义。 |
| `fliki-clone-api/tests/test_track25_quota_sse.py` | 测试（**新文件**）| **10 case**：(1) `publish_user_event` 写 `user:{user_id}:stream` + pub/sub 双写；(2) 空 user_id noop；(3) sync redis 不可用 noop；(4-5) `reserve_tenant` 超限抛 `quota_exceeded` + 不传 user_id 时**不**抛事件；(6-7) `acquire` BucketFull 抛 `bucket_full` + 不传 user_id 时**不**抛事件；(8) `subscribe_user` 把 `last_event_id` 透传给 `xread({user:{u}:stream: cursor})`；(9) 空 user_id 走空迭代器；(10) `__all__` 导出 sanity。 |

## 2. 烟测命令 + 结果

### 2.1 单元 + 集成
```bash
cd /Users/zhaoguangyuan/project/empty-track25/fliki-clone-api
/Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest -v
# 99 passed in 2.09s
```

按文件细分：
```
tests/test_admin_flags.py .......        [7 PASS]
tests/test_art_v3.py ........            [8 PASS]
tests/test_billing_webhook.py ......     [6 PASS]
tests/test_canary_multichar_combo.py ... [4 PASS]
tests/test_dlq_retry_publish.py .......  [7 PASS]
tests/test_publishing.py ........        [8 PASS]
tests/test_quota_v2.py ........          [8 PASS]
tests/test_track09_multichar.py ......   [6 PASS]
tests/test_track17_sse_resume.py .......... [10 PASS]
tests/test_track18_cost.py ..........    [10 PASS]
tests/test_track25_quota_sse.py .......... [10 PASS] ← Track-25 新增
tests/test_voice_v4.py .......           [7 PASS]
tests/test_youtube_chunked_upload.py .... [8 PASS]
```

### 2.2 路由烟测（确认 SSE 端点 mount）
```bash
.venv/bin/python -c "from app.main import app; \
  routes=[r.path for r in app.routes]; \
  assert '/api/pipelines/user-events' in routes; \
  print('mounted:', sorted(r for r in routes if 'user-events' in r))"
# mounted: ['/api/pipelines/user-events']
# 总路由数 121（baseline 120 + 1 新增）
```

### 2.3 真启 backend + curl（user 自验证；本 session 沙盒 redis 未启动跳过）
```bash
# 起 redis + backend
brew services start redis
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 拿一份带 cookie 的 curl（先在浏览器登录后从 DevTools 拷 cookie）
curl -N -H "Accept: text/event-stream" \
     -b "session=...; ..." \
     http://127.0.0.1:8000/api/pipelines/user-events
# 应立刻收到一行 `event: snapshot` + `data: {...}` 含 quota/buckets
# 再开第二个 terminal 起一次会超额的 pipeline 启动 → 第一个 terminal 应收到
# `event: quota_exceeded` + payload 含 attempted_cost/monthly_limit/current_usage
```

### 2.4 前端烟测建议（本 session 不跑：worktree 共享 node_modules + Next 已 hot-reload）
1. 浏览器进 `/zh/app/...`，DevTools Network 应看到一条挂着的 `user-events` SSE 长连接
2. 把某个 tenant 的 monthly_limit_usd 调到 1.0，再启动一次 video_full → 应弹红色 toast「月度额度不足，剩余 $X」
3. 把 `provider_concurrency_buckets.max_concurrent` 设成 1 + `current_in_flight=1` → 启动新 run 直到 hits Provider → 应弹琥珀 warning「Provider {name} 并发到上限，请稍后」

## 3. 设计要点 / 安全边界

1. **完全沿用 Track-17 内核**：`publish_user_event` 调的是同一份 `_publish_to_channel`（双写 redis Stream + pub/sub）；`subscribe_user` 调的是同一份 `_subscribe_channel`（XREAD + Last-Event-ID 续传 + 1s idle yield）。不重复代码、不引新依赖。
2. **频道隔离**：`user:{user_id}` 与 `pipeline:run:{run_id}` / `publish:plan:{plan_id}` 三套频道命名空间互斥；订阅各走各的，broadcast 不串。
3. **向后兼容**：`reserve_tenant(... user_id=None)` 与 `acquire(... user_id=None)` 都是新加 kwarg，老调用方（VoiceAgent / EditAgent / 其它历史路径调过 reserve_tenant 的少数老脚本）行为完全不变；只在显式传 user_id 时才走事件分支。
4. **publish 失败不阻断业务**：reserve / acquire 内部 `try: publish_user_event(...) except: warning`；redis 抖动时业务仍正常返回 ok=False / 抛 BucketFull，前端拿 HTTP 错误也能 fallback。
5. **前端去重 + Last-Event-ID 续传**：同事件 1.5s 内去重防刷屏；onerror 不主动 close 让浏览器原生重连续传，与 Track-17 设计一致。
6. **layout 一行挂载**：`(app)/layout.tsx` 仍是 server component（保留 `force-dynamic`），通过 thin client wrapper `<UserEventsListener />` 实现一行挂上全局 hook，不污染 layout 路由层级。
7. **互斥锁严格遵守**：`events.py` 只**新加**函数（不动 `_publish_to_channel` / `_subscribe_channel` 内核与既有 `publish` / `publish_plan_event`）；`quota.py::reserve_tenant` 只在末尾失败分支加事件路径；`provider_buckets.py::acquire` 只在 BucketFull 抛之前加事件路径；`routers/pipelines.py` 只在文件末尾加 SSE 段，不动既有 `/events` / `/quota` / `/buckets`；alembic / .env / config.py / billing / dlq / publishing 全未触碰。

## 4. 已知边界 / 跳过的子任务

- **没在 cancel / runner._settle_run_state 推 quota_recovered 事件**：v1 范围只覆盖「负向」事件（红色 toast / warning），后续可加正向「额度恢复」绿 toast，前端可对照 snapshot 自动刷数。
- **没做 SSE fallback polling**：用户级 SSE 是「全局轻量」长连接，断流时浏览器原生重连足够；不像 pipeline run 流即使断也要保 UI 不黑屏，所以没必要起 polling 兜底。
- **没改 `/api/pipelines/quota` 字段**：snapshot payload 与 `/quota` 字段一致，前端拿 SSE snapshot 即可降级出 toast 文案，不强制把 `/quota` 替换成 SSE。
- **没把 quota_exceeded / bucket_full 写 audit log**：纯前端反馈通道；ops 想审计仍应从 `model_calls.status=RATE_LIMITED` 与 router 402 错误日志查。

## 5. Follow-up 建议

| 触发 | 建议 |
|---|---|
| Track-25 合 main 后 | 在 SESSION_HANDOFF.md 「能力扩展」表加一行：用户级 SSE 实时反馈（quota_exceeded / bucket_full），前端 layout 全局挂载，与 Track-17 redis Stream 内核共享 |
| L-04 月账单（Track-22）合并后 | 复用同一 `user:{user_id}` 频道推 `invoice_paid` / `payment_failed` 事件，让前端立刻看到付款成功 / 失败 toast，不依赖刷新 billing 页 |
| L-05 真 RBAC（Track-24） | `subscribe_user` 可扩展鉴权：admin 订阅他人 user channel 时走 RBAC.get_user_role 决定是否允许；目前只允许订阅自己 |
| 监控 | Prometheus 指标 `user_events_published_total{kind=...}` / `user_events_subscribers_active`，便于发现 SSE 长连接堆积 |

## 6. commit 完整性

```bash
git status
# On branch track-25-quota-exceeded-sse
# nothing to commit, working tree clean
```

T-14 教训：完成代码后已自验 `git status`，working tree clean。
