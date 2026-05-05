# ADR-004：多平台发布执行器 SLA 与重试策略

- 状态：Accepted
- 日期：2026-05-05
- 决策人：fliki-clone 团队
- 关联 Track：Track-02 (`confirm_real_publish` 列) / Track-03 (publish 异步化 + SSE) /
  Track-13 (YouTube chunked PUT + 进度回写) / Track-15 (DLQ retry 按 task_name 路由) / Track-16 (Stripe webhook + refund)
- 关联文档：`docs/adr/003-credentials-encryption.md`、`SESSION_HANDOFF.md`

---

## 背景

v1 收口前发布执行器已经从「同步 multipart 一把发」演进到「Celery 异步 + 8 MiB chunked PUT + DLQ retry 按 task_name 路由」。
落地涉及 4 个 Track，行为细节散落在多个文件 / commit message：

- `services/publishing/adapters/{base,dry_run,youtube,bilibili}.py`：3 个 adapter + 协议
- `services/publishing/executor.py`：执行器主入口（凭证加载、安全闸门、进度回写）
- `services/publishing/oauth.py`：OAuth state / token 换 / refresh
- `services/pipeline/tasks.py`：Celery 入口 `execute_publish_plan_task` + 共享体 `_publish_execute_with_events`
- `services/pipeline/dlq.py` + `routers/dlq.py::_retry_dispatch`：DLQ push / retry 路由

新增第三方平台（TikTok / Instagram Reels / 真 Bilibili / 视频号）时，需要一份**单一可信源**回答：

- 这平台是 stub 还是真发？
- 失败怎么分类（业务级 vs 系统级）？
- 重试策略是什么（哪些 HTTP code 退避、退避节奏、上限）？
- DLQ retry 怎么路由回正确的 task？
- 凭证刷新是 adapter 自管还是 executor 透传？
- SSE 进度推送在哪些片段触发？

本 ADR 把这套约定固化下来，作为新平台 adapter 的 onboarding checklist。

## 分类原则（核心约定）

### 失败分类二元化

| 类型 | adapter 行为 | executor 处理 | UI 表现 | 例子 |
|---|---|---|---|---|
| 业务级失败 | 返 `PublishOutcome(ok=False, error=...)` | `plan.status='failed' + plan.error=...`；**不入 DLQ** | 红色卡片 + 错误文案 + 引导用户操作 | 缺 OAuth scope / 缺 KEY / 平台拒收 metadata / `confirm_real_publish=false` 闸门下的拒发 |
| 系统级失败 | 抛 `PublishError(...)` | DLQ push（`task_name=publish.execute_plan` + args=[plan_id] + kwargs.user_id）；plan 不变 | 死信卡片 + retry 按钮 | 网络断 / 5xx / 429 重试耗尽 / token refresh 网络层异常 |

为什么二元化：业务级失败大多需要用户主动操作（重新 OAuth、补 metadata、关安全闸门），自动 retry 没意义；
系统级失败大概率是瞬时网络抖动，DLQ retry 后能自愈。混在一起会让 retry 按钮变成"瞎点"。

### 安全闸门（Track-02）

`PublishRequest.confirm_real_publish: bool = False`（默认）控制 adapter 是否真打外部 API：

- `adapters/base.py` 第 52-54 行声明字段语义
- `executor.py` 第 101 行从 `publish_plans.confirm_real_publish` 列直接读出（独立列；不是 meta_json 隐藏字段）
- 真发 adapter（YouTube）必须在 upload 入口检查；False 时返 `PublishOutcome(ok=True, external_id="youtube-pending-...")`
  让 UI 流程闭环 + 不真发（`adapters/youtube.py` 行 128-157）

价值：dev / 测试 / 演示 demo 都能跑全发布流程而不真发到生产渠道；要真发用户得在 UI 显式打开 toggle。

## SLA 决策矩阵

每个 adapter 一段；新增平台时复制本格式追加。

### dry-run（永远可用的兜底）

- **真发**：False（`adapters/dry_run.py::DryRunAdapter.is_real=False`）
- **OAuth**：不需要（`requires_credential=False`）
- **SLA**：100% 成功；返 `external_id="dryrun-{plan_id[:8]}-{ts}"`、`external_url=https://dry-run.local/v/...`
- **失败分类**：永远 `ok=True`；不入 DLQ
- **延迟**：< 50ms（无网络调用）
- **使用场景**：用户主动选 dry-run 演示 / `get_adapter()` 在未知平台时回退（`adapters/base.py::get_adapter` 第 114-121 行）
- **新平台 onboarding**：`register_adapter("dry-run")` 是项目第一个被 import 的 adapter，
  `_REGISTRY` 必含；任何新平台 adapter 出 import error 都不影响 dry-run 兜底

### youtube（v1 主真发渠道）

- **真发**：True（`adapters/youtube.py::YouTubeAdapter.is_real=True`）
- **OAuth**：需要（`requires_credential=True`）；scope 必须含 `https://www.googleapis.com/auth/youtube.upload`
- **上传协议**：resumable upload v2，分两阶段：
  1. `_initiate_resumable_upload`（行 265-299）POST 拿 session uri；带 `X-Upload-Content-Length` 预声明
  2. `_chunked_put`（行 302-407）按 8 MiB（`DEFAULT_CHUNK_SIZE = 8*1024*1024`）切片 PUT，
     `Content-Range: bytes X-Y/total`
- **重试矩阵（单片）**：
  - HTTP 200/201：最后片成功，body 含 `{id: video_id}` → 返
  - HTTP 308：该片成功，进入下一片
  - HTTP 5xx / 408 / 429：指数退避 1s/2s/4s（`_backoff` 行 436-445），单片最多重试 3 次（`MAX_RETRIES_PER_CHUNK`）
  - 其它 4xx：立即抛 `PublishError`（不可恢复 → DLQ）
  - `requests.RequestException` 网络层异常：按可重试 5xx 处理
- **预期延迟**：60 MB / 1080p 60s 视频 ≈ 3-5 min（含 download render_url + upload + Google 后处理）；
  300 MB / 1080p 4-5 min 视频 ≈ 10-15 min
- **SSE 进度**：每片完调一次 `progress_cb({phase, bytes_uploaded, total, percent, chunk_index, chunk_count})`，
  executor 把 info 落 `publish_plans.meta_json.upload_progress` + 推 SSE `upload_progress` 事件
- **凭证生命周期**：
  - `refresh_token` 长期有效（除非用户主动 revoke）→ Fernet 加密落 `platform_credentials.refresh_token`
  - `access_token` 1h 过期 → adapter 在 upload 入口检查 `cred.expires_at < now()`，命中即调 `_refresh_youtube_token`
    （行 448-474）拿新 access_token；refresh 失败抛 `PublishError`（系统级 → DLQ；retry 时 user 重新 OAuth）
  - 刷新成功后 `outcome.credential_update={access_token, expires_at}`，executor 调 `creds.update_after_publish` 回写
    （`executor.py` 行 114-122；加密走 `credentials._encrypt`）
- **安全闸门**：`req.confirm_real_publish=False` 时返 mock external_id，**不真发** + 不消耗 quota
- **失败分类示例**：
  - 缺 `GOOGLE_CLIENT_ID/SECRET` → 业务级（行 74-83）
  - 用户未授权（无 access_token）→ 业务级（行 92-97）
  - scope 不足 → 业务级（行 99-107）
  - `render_url` 空 → 业务级（行 109-114）
  - download render 网络异常 → 系统级 `PublishError`（行 162-165）
  - initiate session 5xx → 系统级（行 286-289）
  - chunk PUT 重试耗尽 → 系统级（行 390-394）
  - chunk PUT 4xx 不可恢复 → 系统级（行 398-402）

### bilibili（v1 stub，等 MCN 入驻）

- **真发**：False（`adapters/bilibili.py::BilibiliAdapter.is_real=False`）
- **OAuth**：不需要（`requires_credential=False`）
- **行为**：永远返 `PublishOutcome(ok=False, error="bilibili 自动发布尚未实现：...请手动下载 render 视频后到 https://member.bilibili.com 上传：{render_url}")`
- **失败分类**：业务级（不入 DLQ）；UI 显示清晰的「手动上传引导」
- **不入 DLQ 的原因**：retry 也不会真发；DLQ 只为「能自愈的瞬时失败」服务
- **未来真适配**：MCN / 合作伙伴 OpenAPI 拿到 → Track-12 重写 BilibiliAdapter，
  `is_real=True` + `requires_credential=True`；本 ADR 矩阵增补一行 + 不替换 stub 文件，
  避免 dev 环境无凭证时硬卡

## 重试策略（DLQ）

### push 路径

入 DLQ 的两个入口（`services/pipeline/dlq.py::push`）：

1. Celery worker：`Task.on_failure` hook（acks_late 重发耗尽时）
2. BackgroundTasks：`_publish_execute_with_events` 内部捕获 `PublishError` 后显式 push（带 `user_id` + plan args）

幂等：`(task_name, args)` 软去重，同 logical task 反复失败 → 同一行 `attempt_count++`，不重复建行（`dlq.py` 行 78-108）。

### retry 分发（Track-15）

`routers/dlq.py::_retry_dispatch`（行 140-206）按 `task_name` 路由：

```
publish.execute_plan
  ├─ celery 模式  → execute_publish_plan_task.apply_async(args=[plan_id], kwargs={user_id}, queue="default")
  └─ BG 模式      → background_tasks.add_task(_publish_execute_with_events, plan_id, user_id)

pipeline.tick / pipeline.execute_step / background.tick
  ├─ celery 模式  → tick_task.delay(run_id)
  └─ BG 模式      → background_tasks.add_task(tick, run_id)
```

为什么按 `task_name` 路由：v1 旧版本把所有死信都丢进 `tick_task`，publish 死信会被错误执行成
"tick 一个不存在的 run id" 直接 settle，发布从未真重投。Track-15 通过 task_name 显式分发修复。

### retry 限制

- 仅 `status='pending'` 可 retry；`retried / discarded` 不能再次 retry（`routers/dlq.py::retry_dlq` 行 102-106）
- retry 后立刻把 DLQ 项标 `retried`；如果再次失败会**新增一行**（不复用旧行，便于审计 attempt 历史）
- 重试**不重新预扣 quota**：执行器幂等，retry 走的是与首次发起完全相同的 plan_id 上下文；
  v1 不做 quota refund / re-charge（业务级失败本身没扣 quota；系统级失败 plan 状态仍是 in-flight）

### 不做的事

- **不做**自动 retry 调度（cron / 定时扫 DLQ 自动重投）：v1 让用户主动点 retry；
  防止 5xx 永久故障时无限自动重试雪崩
- **不做**批量 retry：DLQ panel 一条一条 retry，便于审计
- **不做**全局 time_limit 硬超时：YouTube 上传上限就是 task 上限；celery 队列层不再加超时

## 凭证生命周期（与 ADR-003 衔接）

```
用户点「绑定 YouTube」
    ↓
oauth.py::build_state  生成 JWT state（user_id+platform+nonce, 1h 过期）
    ↓
跳 Google OAuth → 用户授权 → callback 带 code + state
    ↓
oauth.py::handle_callback  POST GOOGLE_TOKEN_URL 换 access_token + refresh_token
    ↓
credentials.py::upsert_credential  Fernet 加密 access/refresh → 落库（platform_credentials）
    ↓
首次 publish 触发 → executor.py::execute_publish_plan
    ├─ creds.get_credential(user_id, platform)  → 解密 plain text 给 adapter
    ├─ adapter.upload(req)
    │   └─ 检查 expires_at；过期 → _refresh_youtube_token → outcome.credential_update={access_token, expires_at}
    └─ creds.update_after_publish  → Fernet 加密回写（refresh_token 保留）

refresh_token 失效（用户改密码 / revoke）
    ↓
adapter._refresh_youtube_token 抛 PublishError "youtube refresh http 401"
    ↓
executor 入 DLQ；UI 显示「YouTube 凭证失效，请重新绑定」
    ↓
用户重新点「绑定 YouTube」从头来一遍
```

## 后果与权衡

| 维度 | 取舍 |
|---|---|
| 新平台 onboarding | adapter 协议简单（`PublishRequest → PublishOutcome` + `PublishError`），1 天能写一个新平台 |
| 测试摩擦 | dry-run 兜底 + `confirm_real_publish` 闸门让单元 / 集成测试不需要真账号 |
| DLQ 可观测 | 死信表分类清晰（task_name + run_id + step_id + user_id）；前端 panel 直接 retry / discard |
| 重试雪崩 | 单片 3 次 + 用户主动 retry；不引入 cron 自动重试；可控 |
| 凭证泄漏 | Fernet 加密落库（ADR-003）；adapter 协议拿到的是 plain text，但仅在内存中、单次发布生命周期内 |
| YouTube 上传时长 | 60 MB ≈ 3-5 min，1080p 长视频可能 10+ min，celery worker 必须配 long-running 队列；本 ADR 选 `default` 队列 |
| 业务级 vs 系统级误判 | 一条规则统一了 adapter 行为：能自愈的瞬时失败抛 `PublishError`；其它返 `ok=False`。审 PR 时单点检查 |

## 不做什么（明确边界）

- **不做** TikTok / Instagram Reels / 视频号适配（v1 范围之外；商务接入 + 真账号 e2e 完成后再加 adapter）
- **不做** 跨平台并发发布（一个 plan = 一个 platform；多平台同步发用多条 plan）
- **不做** 调度发布（`scheduled_at` 字段已留但 v1 不真定时；走 plan = active 立即发布）
- **不做** retry 时换 adapter / 换 platform：retry 严格走原 plan_id 路径
- **不做** 上传到 R2 / S3 中转：v1 直接从 `render_url` 流到 YouTube；render 服务自身保证 url 至少 30 min 可访问

## 重新评估触发条件

满足任一即开 ADR-XXX 评估升级：

1. 单 plan 真发延迟 > 30 min（说明 chunked PUT 太碎或网络层有大问题）
2. DLQ pending 数持续 > 100 条 / 24h（自动 retry 调度 + 重试上限策略需要量化）
3. 同时支持 4+ 真发平台（adapter 矩阵开始爆炸，需要标准化 SDK / 测试夹具）
4. 出现「真发后 token 在 5 min 内失效」的 OAuth provider（refresh 节奏需要从被动改主动预 refresh）

## 引用

- adapter 协议：`app/services/publishing/adapters/base.py`
  （`PublishRequest` 行 30-60、`PublishOutcome` 行 63-75、`PublishError` 行 78-79、`get_adapter` 行 114-121）
- adapter 实现：
  - `adapters/dry_run.py::DryRunAdapter`（行 25-52）
  - `adapters/youtube.py::YouTubeAdapter`（行 67-216；helper 行 222-474）
  - `adapters/bilibili.py::BilibiliAdapter`（行 25-40）
- 执行器：`app/services/publishing/executor.py`（`execute_publish_plan` 行 43-130；progress_cb 注入 行 79-103）
- OAuth：`app/services/publishing/oauth.py`（`build_state` 行 50-61、`handle_callback`）
- DLQ：
  - service：`app/services/pipeline/dlq.py`（`push` 行 51-138 含软去重 78-108）
  - 路由：`app/routers/dlq.py`（`retry_dlq` 行 91-114、`_retry_dispatch` 行 140-206）
- Celery / BG 双模式：`app/services/pipeline/tasks.py`
  （`_publish_execute_with_events` 行 192、`execute_publish_plan_task` 行 301-306）
- 安全闸门列：alembic `9c2d4e5f6a7b`（Track-02）`publish_plans.confirm_real_publish`
- 上下游 ADR：ADR-001（工作流引擎）/ ADR-002（Agent 编排）/ ADR-003（凭证加密）
