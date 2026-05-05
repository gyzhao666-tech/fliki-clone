# 跨会话交接（2026-05-04 全天 → 2026-05-05 全天：v1 工程闭环全部收口 → 多 Agent 第一波 7 + 第二波 4 + 第三波 5 + 第四波 1 + 第五波 4 + 第六波 1 = 22 Track 全合）

> 这一份是"贴到下个会话开头就能无缝接力"的最小集；详细技术点在 `DEVELOPMENT_PLAN.md` 第 13 节。
> 关键约束 / 已知坑请认真读完再写代码。

> 2026-05-05 16:30 更新：**Track-24 RBAC v1 已合并到 main**（`pytest 130/130 PASS`）。
> 第六波 1 Track（T-24）；alembic head 升到 **`d4e5f6a7b8c9`**（顶 `c3d4e5f6a7b8`，
> `team_members.role` 列 + ix 索引 + 一次性 backfill workspace owner = `admin`）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 24 RBAC v1（workspace member role + 邮箱白名单 fallback）| `team_members` 加 `role: VARCHAR(20) DEFAULT 'editor'` 列 + index；alembic 一次性 backfill：`UPDATE team_members tm SET role='admin' FROM workspaces w WHERE tm.workspace_id=w.id AND tm.user_id=w.owner_id`（owner 自动 admin，其他保留 editor）；新模块 `services/auth/{__init__,rbac}.py`：`get_user_role(user_id, workspace_id)` + `is_admin(user_id, *, workspace_id=None, email=None)` 三路径（explicit workspace → 任意 workspace → 邮箱白名单 fallback）+ 60s 内存缓存（同 `pipeline/tenant.py` pattern）；`routers/admin_flags.py::_require_admin` + `routers/cost.py::_resolve_query_tenant` admin 判定切到 `rbac.is_admin`，`_is_admin_email` 保留作 fallback 兜底（不删，dev `demo@example.com` 兼容）；前端 `lib/admin-flags.ts::getAdminMe` 返 schema 不变；10 case 单测覆盖三路径 + cache TTL + alembic 列存在 + owner backfill |
>
> **整体能力扩展**：admin 后台从邮箱白名单升级为 workspace member role（admin/editor/viewer），与 multi-tenant 配额体系（Track-09 多角色 / Track-10 canary / Track-18 model_calls.tenant_id）一致；为后续 workspace 协作权限分级（editor 改改、viewer 只看）打下基础。

> **🎉 v1 工程闭环全部收口**：22 个 Track 合并完毕（10 天工作量浓缩在一天），`pytest 130 PASS`，
> 5 条 alembic 迁移全落库，125+1=126 路由（含 v1 全部业务 + admin + cost + RBAC）。
> 距离真正上线只差 **T-20 真账号 e2e**（半天，**非代码**：用户配 `.env` 真 key 跑一次完整链路）。

> 2026-05-05 15:50 更新：**多 Agent 第五波 4 Track 已合并到 main**（`pytest 120/120 PASS`）。
> 合并顺序：T-25 → T-22 → T-21 → T-23（T-23 留最后吸收 `.env.example` 顶部 SMTP_* + ADMIN_EMAILS 区域冲突；
> `app/config.py` 由 git auto-merge 自动并入两组字段）。alembic head 仍是 **`c3d4e5f6a7b8`**（本批没人占）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 21 metric dashboard（cost 时序图 + admin metrics 页）| `routers/cost.py` 末尾追加 `GET /api/cost/timeseries?tenant_id=&provider=&period=daily\|weekly&days=30`：SQL `DATE_TRUNC('day'/'week', created_at)` GROUP BY day, provider 聚合，返 `[{date, provider, cost_usd, call_count}]`；复用既有 `_resolve_query_tenant` 鉴权；不动既有 `/summary` `/recent`；新前端 `app/[locale]/(app)/app/admin/metrics/page.tsx`（939 行）：tenant 选择器 + provider 多选 chips + period toggle + recharts LineChart 多 series（每 provider 一条折线）+ 顶部数字 total_cost / total_calls；`lib/cost.ts` 加 `getCostTimeseries` + `CostTimeseriesPoint`；`sidebar.tsx` admin 命中渲「Admin · Metrics」入口与 Feature Flags 并列；8 case 单测 |
> | 22 月账单 PDF + SMTP 邮件（invoice.paid）| `requirements.txt` 加 `reportlab>=4.0`；`config.py` 加 5 条 `SMTP_*` 字段 + `invoice_email_enabled: bool = False`（缺省关闭防误发）；`.env.example` 加 SMTP 配置说明；新 `services/billing/invoice_pdf.py`（382 行）reportlab 渲 A4 PDF 含 plan + period + 按 provider cost 表 + 总金额（数据源 stripe invoice + T-18 model_calls 期内明细）；新 `services/email/{__init__,smtp_client}.py` 薄封装 stdlib smtplib（缺 SMTP 抛 EmailNotConfigured，不引第三方依赖）；`webhook_handlers.py` 加 `invoice.paid` dispatch + `_handle_invoice_paid`：`invoice_email_enabled=False` 返 `{handled:True, sent:False, reason:...}` 让 stripe 不重投；与 T-16 既有 5 handler 共存；7 case 单测 |
> | 23 ADMIN_EMAILS 迁回 Settings | `config.py` 加 `admin_emails: str = "demo@example.com"` 字段（pydantic-settings 自动从 env 读，逗号分隔）；`routers/admin_flags.py::_allowed_admins()` 改读 `get_settings().admin_emails`，按逗号 split + strip + lower + 去空 + set 化；保留 `demo@example.com` 兜底（dev fixtures 兼容）；T-10/14/18 既有调用方走 `_is_admin_email` 不变；`tests/test_admin_flags.py` 既有 7 case 用 monkeypatch settings 替代 `os.environ.set` 注入；6 case 新单测 |
> | 25 配额超限 / Provider 桶满 SSE 实时推送 | `services/pipeline/events.py` 复用 `_publish_to_channel`/`_subscribe_channel` 内核，新加 `publish_user_event(user_id, event_type, payload)` + `subscribe_user(user_id, *, last_event_id, stop_event)` async iterator；channel `user:{user_id}` 与 `pipeline:run` / `publish:plan` 互不打扰；redis Stream + pub/sub 双写继承 T-17 断网续传能力；`quota.reserve_tenant` 抛 402 之前调 `publish_user_event(user_id, "quota_exceeded", {...})`；`provider_buckets.acquire` BucketFull 时调 `publish_user_event(..., "bucket_full", {...})`；`gateway.py` 把 user_id 透传给 bucket acquire；新路由 `GET /api/pipelines/user-events` SSE（owner 鉴权 CurrentUser.id == channel user_id，snapshot+增量）；前端新 hook `use-user-events.ts` + `<UserEventsListener/>` client component 挂在 `(app)/layout.tsx` 全局生效，监听 `quota_exceeded` → `feedback.error` toast / `bucket_full` → `feedback.warning` toast；10 case 单测 |
>
> **整体能力扩展**：v1 上线后的可观测性（按天/provider 时序图 cost dashboard）+ 计费收口（月账单 PDF 邮件自动发）+ 平台清洁度（admin 配置 .env settings 化）+ 用户体验（配额超限/满桶提前 toast 不再突然 402/429）。

> 2026-05-05 15:00 更新：**Track-18 已合并到 main**（`pytest 89/89 PASS`）。
> alembic head 升到 **`c3d4e5f6a7b8`**（顶 `b2c3d4e5f6a7`，`model_calls.tenant_id` 列 + 索引 + 一次性 backfill 老行为 `u:{user_id}`）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 18 model_calls 加 tenant_id + 按 tenant 聚合 cost 视图 | `model_calls` 加 `tenant_id` 列 + 普通索引；`gateway.record_call` 透传 `request.tenant_id`，缺失兜底 `u:{user_id}`（与 `pipeline.tenant.resolve_tenant_id` 同一约定）；新 `routers/cost.py` 2 端点：`GET /api/cost/summary?tenant_id=&period=monthly\|weekly\|daily`（按 provider 聚合 cost_usd / call_count / success_count / failed_count）+ `GET /api/cost/recent?tenant_id=&limit=`；admin 邮箱可指定他人 tenant_id 否则静默覆盖回自己；前端 4 格 stat 下方折叠 cost panel 按 provider 横向 bar（emerald=OpenAI / sky=SiliconFlow / amber=Kling / violet=ElevenLabs / slate=local），与 quota refreshQuota 同生命周期 | alembic `c3d4e5f6a7b8` + `models/model_call.py` 加列 + `services/model_gateway/{cost,gateway}.py` + 新 `routers/cost.py` + 新 `lib/cost.ts` + `pipeline/page.tsx::CostBreakdownPanel` + 10 case 单测（4 unit + 6 integration） |

> 2026-05-05 14:30 更新：**多 Agent 第三波 5 Track 已合并到 main**（`pytest 79/79 PASS`）。
> 合并顺序：T-15 → T-14 → T-13 → T-17 → T-16（T-17 vs T-13 在 use-publish-plan-stream.ts 顶部 docstring 段一处冲突，已手解保留双方协议描述）。
> 新 alembic head: **`b2c3d4e5f6a7`**（顶 `a1b2c3d4e5f6`，`subscriptions.refunded_at` 列）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 13 YouTube chunked PUT + 进度回写 SSE | YouTube adapter 删 v1 multipart 一把发；改成 8 MiB 分片 chunked PUT；每片 5xx/408/429 指数退避重试 3 次；`progress_cb` 每片调用一次 → executor 闭包 read-modify-write `publish_plans.meta_json.upload_progress` + `publish_plan_event(plan_id, "upload_progress", info)` 推 SSE；前端新 `<UploadProgressBar>`（下载灰 / 上传 sky）+ `latestProgress` state | `adapters/youtube.py` 重写 + `adapters/base.py` `progress_cb` 字段 + `executor.py` `_make_progress_cb` + `use-publish-plan-stream.ts` `addEventListener("upload_progress")` + `pipeline/page.tsx::PlanRow` 进度条段 + 8 case 协议层 mock 单测 |
> | 14 Admin Feature Flags UI | 后端 `routers/admin_flags.py` 抽 `_is_admin_email`；新加 `GET /me`（任何登录用户可调返 `{is_admin, email}` 让前端探测）+ `GET /tenants`（按 tenant_id 聚合 + flag_count）；新前端 `app/admin/feature-flags/page.tsx`（968 行 tenant 选择器 + 表格 + pct 滑块 / toggle / variant 下拉自适应 + Apply/Delete + 新增 dialog）+ `lib/admin-flags.ts` + `sidebar.tsx` admin 入口 | 7 case 单测覆盖白名单 / `_require_admin` 403 / `/me` / `/tenants` / CRUD round-trip。**注**：agent 完成代码 + 测试但忘 commit + NOTES，协调者 `git add -A` 收口 + 代写 NOTES |
> | 15 DLQ retry 按 task_name 路由 | `routers/dlq.py::_retry_dispatch` 识别 `task_name="publish.execute_plan"` 改派 `execute_publish_plan_task`（celery）/ `_publish_execute_with_events`（BG fallback）；顺手修隐藏 bug：旧版 `if not run_id: 400` 让 publish DLQ 死锁（`publish_plans` 与 `pipeline_runs` 没外键，task 没 `run_id`） | `routers/dlq.py` 加 task_name 分支 + 7 case 单测覆盖 celery / BG / args 解析 / 兜底 task_name=tick / 已 retried 拒绝 |
> | 16 Stripe webhook charge.refunded + 6 case 单测 | alembic `b2c3d4e5f6a7` 顶 `a1b2c3d4e5f6`，加 `subscriptions.refunded_at TIMESTAMPTZ NULL`（不加 server_default 避免老行误打标 / 不加索引）；`webhook_handlers.py` 加 `_handle_charge_refunded`：`metadata.subscription_id` → `customer` 反查最新订阅；都不命中返 `{handled:True, matched:0}`；**只打标 refunded_at**，不动 `tenant_quotas` / `users.plan` / `subscriptions.plan`（v1 用户体验优先；ops 评估后人手降级）；6 case 端到端覆盖 5 类 stripe 事件 + unknown | `alembic/versions/20260505_1500_add_subscription_refunded_at.py` + `models/billing.py::Subscription` 加列 + `services/billing/webhook_handlers.py` 加 handler + 新 `tests/test_billing_webhook.py` |
> | 17 SSE 断网重连 last_event_id | `services/pipeline/events.py` 升级为 redis Stream + pub/sub 双写：`_publish_to_channel` 加 `XADD {channel}:stream * data <json>`（MAXLEN ~1000 approximate trim）；`_subscribe_channel` 改用 `xread({stream: cursor}, block=1000)`；yield 升级 3-tuple 带 `entry_id`；XADD 失败不阻塞 PUBLISH；`_sse_format(event, data, event_id=None)` 非空时 emit `id:` 行；两个 SSE 端点从 `Last-Event-ID` 头透传 cursor → 浏览器 EventSource 自动续传 | `events.py` 重写 + `routers/{pipelines,production}.py::_sse_format` + 两个前端 hook + 10 case 单测（XADD 双写 / 失败兜底 / cursor 推进 / id 单调 / redis ping 失败 noop） |
>
> **整体能力扩展**：YouTube 1080p+ 真发不再卡 60s timeout（chunked PUT + 进度条 UI）；DLQ retry 真能重投 publish 任务（修了「按钮点不动 + 静默 retried 误导审计」的 bug）；Admin Feature Flags 可视化（不再 curl）；Stripe 退款事件全闭环；SSE 断网重连续传不丢中间事件。

> 2026-05-05 13:55 更新：**多 Agent 第二波 4 Track 已合并到 main**（`pytest 41/41 PASS`）。
> 合并顺序：T11 → T03 → T09 → T10（最后合 T10 解 art.py canary × 多角色叠加冲突）。
> 新 alembic head: **`a1b2c3d4e5f6`**（顶 `9c2d4e5f6a7b`，`feature_flags` 表）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 03 publish 异步化 | `POST /publish-plans/{id}/execute` 默认返 202+`events_url` 走 celery（`?sync=true` 兜底走 v1 同步）；新 SSE `GET /publish-plans/{id}/events`：`snapshot`+`publish_plan_state(running\|completed\|system_error)`+25s ping；celery task `publish.execute_plan`（queue=default）；BackgroundTasks fallback 共用同一 task body | `services/pipeline/{events,tasks,celery_app}.py` + `routers/production.py` + 新 `hooks/use-publish-plan-stream.ts` + PlanRow 行内 stream/poll 徽标 + Loader spin |
> | 09 多角色锁定 v5 | ArtAgent 从「只锁主角」升级为「每个 character_card 各一份 anchor」+「按 `shot.focus_character` 逐镜选对应 anchor」；VideoAgent `_select_ref_image` 跟着按角色选；outputs 加 `character_anchors`/`shots[i].locked_character`/`ref_anchor_role`/`ref_image_summary.by_role`（`character_anchor` 单字段保留为主角的，v3/v4 兼容）；前端 ArtArtifact 多角色 grid（主角 emerald / 配角 violet 边框）+ shots 网格 🔒 角标按角色着色；VideoArtifact 头部按角色统计 | `services/pipeline/agents/{art,video}.py` + `pipeline/page.tsx::{ArtArtifact,VideoArtifact}` + 新 `tests/test_track09_multichar.py` (6 case) |
> | 10 灰度发布 / canary | 新表 `feature_flags(tenant_id, flag_name, value_json)` + 唯一约束 `(tenant_id, flag_name)`；`feature_flags.is_enabled` 支持 `{"pct":0..100}`/`{"enabled":bool}`/`{"variant":...}` 三形态；hash SHA-1 前 8 hex mod 100 跨进程稳定；ArtAgent 入口读 `art_ipadapter_pct` 决定 v4 / v3-prompt-only；outputs 加 `canary_variant` + `canary_flag_value`；admin 路由 `/api/admin/feature-flags`（邮箱白名单） | alembic `a1b2c3d4e5f6` + `models/feature_flag.py` + `services/pipeline/feature_flags.py` + `routers/admin_flags.py` + `runner.execute_step` 注入 `ctx.feature_flags` + `agents/art.py` 入口闸门 |
> | 11 Stripe 计费 v2 | 6 路由 `/api/billing/{plan,checkout-session,portal-session,checkout(legacy),portal(legacy),webhook}`；`services/billing/{stripe_client,webhook_handlers,tenant_sync}.py` 三模块；`quota.update_tenant_plan(tenant_id, new_plan)` 联动 `tenant_quotas` + 遍历 provider buckets `ensure_bucket(plan=new)` bump；webhook 处理 `checkout.session.completed` / `customer.subscription.{updated,deleted}` / `invoice.payment_failed` 4 事件；前端 `/app/billing` 三栏 plan 卡片 + Stripe Checkout/Portal 跳转 | `routers/billing.py` 重写 + `services/billing/*` + `pipeline/quota.py` + 新 `app/billing/page.tsx` + `.env.example`（`STRIPE_PRICE_*`） |
>
> **能力扩展**：发布执行从同步 30-60s 卡 HTTP 升级到异步 202+SSE；角色一致性从「主角 prompt+anchor」升级为「多角色逐镜锁定」；ArtAgent v4 上线 canary 灰度（按 tenant_id hash 染色 0-100%）；Stripe 真支付链路打通（webhook 落 tenant_quotas + provider bucket bump）。

> 2026-05-05 12:35 更新：**多 Agent 第一波 7 Track 已合并到 main**（`pytest 31/31 PASS`）。
> 仓库已 push 到 GitHub: https://github.com/gyzhao666-tech/fliki-clone
> 合并顺序：02 → 01 → 06 → 04 → 05 → 07 → 08（零冲突 ort 自动合）。
> 新 alembic head: **`9c2d4e5f6a7b`**（顶 8b1f6c2d4a93，含 `publish_plans.confirm_real_publish` 列）。
>
> | Track | 内容 | 关键改动 |
> |---|---|---|
> | 01 凭证 Fernet 加密 | `platform_credentials` token 加密落库 + KEY 缺失降级 plain text + warning + 一次性 migrate 脚本 | `app/config.py` + `services/publishing/credentials.py` + `scripts/migrate_encrypt_creds.py` |
> | 02 YouTube 安全闸门 | `confirm_real_publish` 提到独立列；adapter 不再读 `meta_json.plan_meta`；前端 PlanRow toggle + LIVE 红徽标 | alembic 9c2d4e5f6a7b + `models/production.py` + `adapters/{base,youtube}.py` + `executor.py` + `routers/production.py` + `lib/production.ts` + `pipeline/page.tsx::PlanRow` |
> | 04 ArtAgent v4 IP-Adapter | `character_anchor.url` 喂入 image provider；不支持时剥离 `image_url` 重试同模型；前端 IP/IP↓ 二级徽标 | `services/model_gateway/providers/siliconflow_image.py`（兼容 image/image_url 双 key + 降级关键词识别） + `agents/art.py::_generate_keyframes` |
> | 05 VideoAgent v2 | `character_locked=True` 镜用 anchor URL 作 i2v 主参考帧；非主角镜用 keyframe；都缺降级 GENERATE_VIDEO；新输出 `ref_image_source` / `ref_image_url`；前端 RefImageSourceBadge | `agents/video.py` + `pipeline/page.tsx::VideoArtifact` |
> | 06 faster-whisper 本地 fallback | ASR 路由 `[OPENAI, FASTER_WHISPER_LOCAL, SILICONFLOW]`；本地 word-level 离线；输出格式与 OpenAIWhisper 一致；懒导入 + 单例缓存模型 + env 4 个配置项 | 新 `providers/faster_whisper_local.py` + `gateway.py` + `types.py::ProviderName` + `cost.py` + `requirements.txt` |
> | 07 Pipeline DAG 视图 | react-flow（@xyflow/react@12）渲染节点 + 连线 + state 颜色 + 列表/DAG toggle + localStorage 记忆 + 点节点滚动到 step 卡片 + 1.5s 蓝色 ring 高亮 | 新 `components/pipeline/dag-view.tsx` + `package.json` + `pipeline/page.tsx` 顶部 ViewToggle |
> | 08 pytest 工程化 | `tests/` 目录 + conftest fixture（pg_engine / temp_tenant / fake_gateway 等）+ 4 个测试模块（quota_v2 / voice_v4 / art_v3 / publishing）+ 7 个 marker（unit/integration/publishing/quota/voice/art/slow）+ Makefile 加 `test` / `test-unit` / `test-integration` target | `tests/{conftest,test_quota_v2,test_voice_v4,test_art_v3,test_publishing}.py` + `pytest.ini` + `requirements-dev.txt` + `Makefile` |
>
> Track-03（publish 异步化）依赖 02，本次未启动；可在第二波派发。
>
> **整体能力扩展**：YouTube 真发的 toggle 已暴露在 UI（confirm_real_publish 列）；本地 ASR 离线不依赖 OpenAI key；主角跨镜锁定从纯 prompt 升级到「IP-Adapter 接入点 + i2v 主参考帧」联动。

> 2026-05-05 11:30 更新：**发布执行器 v1 已落地**。新表 `platform_credentials`（alembic head
> `8b1f6c2d4a93`）+ `app/services/publishing/`（adapter 协议 + dry-run / youtube / bilibili
> 三 adapter + executor + credentials + oauth）+ `routers/production.py` 新加
> `POST /publish-plans/{id}/execute` / `GET /platforms` / `GET&DELETE /platforms/credentials`
> / `POST /platforms/{platform}/oauth/start` / `GET /platforms/{platform}/oauth/callback`。
> 前端 PlanRow 加「执行」(Upload icon) 按钮 + 错误显示 + external_id 显示；ProductionPanel
> 下方新挂 `<PlatformCredentialsPanel>`：列已注册 adapter（real / stub 徽标）+ 已绑凭证 + 绑定/撤销。
> 端到端测：dry-run 完整链路（reserve→execute→external_id 写回）✓ / youtube 无凭证
> 友好错误 ✓ / bilibili stub 引导手动上传 ✓ / 未知平台 fallback dry-run ✓ / 重复 execute
> 拒绝 ✓。YouTube 真发需 `.env` 配 `GOOGLE_CLIENT_ID/SECRET`；v1 内置「安全闸门」：
> 默认不真发；Track-02 把开关从 `meta_json.confirm_real_publish` 提到独立列
> `publish_plans.confirm_real_publish` + 前端 PlanRow 加 toggle（见上方 Track-02 行）。
>
> 2026-05-05 10:45 更新：**ArtAgent v3 角色一致性已落地**。引入「锚点参考板 + prompt 锁定」
> 双层方案：(1) `_generate_character_anchor` 单独为主角调一次 GENERATE_IMAGE 出 1:1 参考板，
> URL 落 `outputs.character_anchor.url`；(2) `_inject_consistency_into_shots` 把
> `[Consistent character: protagonist=...; appearance=...; wardrobe=...; vibe=...]` 注入
> 到每镜 `enhanced_prompt` 头部，`negative_prompt` 追加 `different face, different person,
> inconsistent character, multiple people` 防漂。`brief.character_consistency` 取值 `auto`
> （默认）/ `prompt-only` / `anchor`（强制）/ `off`；锚点失败时 mode=anchor 自动降到
> prompt-only + 写 `consistency_warning`。`brief.protagonist_role` 显式选主角；缺省取
> `character_cards[0]`。outputs 新字段：`consistency_mode` / `character_anchor` /
> `protagonist_name` / 每镜 `character_locked: bool`。LLM SYSTEM_PROMPT 更新提示主角放第一位
> 且 enhanced_prompt 不重复 character 描述（下游会注入）。前端 ArtArtifact 加 v3 徽标
> （emerald「角色锚点 ✓ v3 · {name}」/ sky「prompt-only」/ muted「一致性 off」+ amber
> 锚点失败警告）+ 锚点缩略图 panel + shots 网格右上角 🔒 角标。烟测 8/8 PASS。
>
> 2026-05-05 10:00 更新：**VoiceAgent v4 word-level 强对齐已落地**。在 v3 之上接入
> `_build_subtitles_v4_word_aligned`：当 ASR 返非空 `words` 且最后 `word.end >=
> audio_dur*0.7` 时进入 v4 路径，按字符比例做 origin↔asr 文本映射，每条 line 的 start/end 从
> 真实 word timestamp 取，每条字幕带 `words: [{start,end,word}]`；单调性矫正 + 边界规整
> （第一条 start=0、最后一条 end=audio_dur）。健康检查降级：words 太少（< lines/2 且 < 5）
> / asr_text 与 origin_text 字符比例 < 0.4 或 > 2.5 → 返 [] 让 caller 退到 v3。outputs 新字段：
> `subtitle_alignment_quality`（`word`/`segment`/`char-ratio`/`shots-duration`）/
> `asr_words_count`。前端 VoiceArtifact 加 violet「word v4 · N words · M/N/K 条」徽标
> + 字幕条「N words」角标 + 紫色 word 时间轴小卡片（前 16 个 word，hover 看时间戳）。
> 算法 + 集成测 6/6 PASS。**激活条件**：`.env` 配 `OPENAI_API_KEY`（VoiceAgent 自动切到
> Whisper-1 拿 word-level）；无 key 时 ASR 路由 fallback SiliconFlow SenseVoice（不返
> words），voice agent 自动降到 v3 行级。
>
> 2026-05-05 09:30 更新：**配额 v2 tenant 级分桶已落地**。新 alembic head `c2f9b7a04ef1`：
> `tenant_quotas`（tenant_id PK + plan + monthly_limit + concurrent_max）+
> `provider_concurrency_buckets`（(tenant_id, provider_name) 唯一）+ `pipeline_runs.tenant_id`
> 列 + 一次性 backfill `u:{user_id}`。新模块 `app/services/pipeline/tenant.py`：
> `resolve_tenant_id(user_id)` 优先 `ws:{workspace.id}` → 兜底 `u:{user_id}` → 匿名
> `anon:default`，1 分钟缓存；`PLAN_DEFAULTS`：free=10/2，standard=100/5，premium=500/10，
> enterprise=5000/30。`quota.py` 加 `get_or_create_tenant` / `reserve_tenant` / `release_tenant`
> / `count_active_runs_tenant`（v1 user 级 API 保留兼容）。新模块 `provider_buckets.py`：
> `acquire`（条件 UPDATE 行锁）/ `release`（GREATEST 兜底防负数）/ `provider_slot` ctx mgr
> / `ensure_bucket` 自带 plan-bump（升级时自动放大 max_concurrent，降级保护已调过的桶）。
> Gateway.run() 入口接入：`request.tenant_id` 显式优先 + 缺失时从 `request.user_id`
> 自动 `resolve_tenant_context` 兜底拿 tenant + plan；桶满返 `CallStatus.RATE_LIMITED`
> 不计费。`/api/pipelines/quota` 加 v2 字段（`tenant_id` / `tenant_plan` /
> `tenant_display_name` / `provider_buckets`）；新增 `/api/pipelines/buckets`。前端 4 格 stat
> 下方新增 tenant 徽标行 + 折叠的「Provider 并发桶」utilization bar（emerald < 70% /
> amber 70-95% / rose >= 95%）。`runner.start_run` 接 `tenant_id`，`_settle_run_state`
> 退还走 tenant；cancel 退还路径同步切换。`_load_run_tenant` 同时读 user.plan 让 ctx 带 plan。
> 端到端验证 PASS：reserve $0.006 → script_only succeeded → cost $0.0021 → cancel 退还
> $0.0039 → tenant.usage 0.006 → 0.0021；429 拦截 5/5 时第 6 次启动被挡（`tenant=u:demo-user-001`
> 出现在错误消息）。烟测 6/6 PASS（tenant_quota / provider_bucket / 并发竞态 20→2 /
> resolver / gateway rate_limited / gateway user_id fallback）。

---

## 2026-05-05 当前进程（最新）

- **后端 pid 30876**（仍在 11:13 启的旧进程；监听 `127.0.0.1:8000`，无 proxy 污染；
  代码改了未重启 → **下次重启会加载第二+三+四+五+六波 15 条 Track 新代码 + alembic head `d4e5f6a7b8c9`**）
- **前端 pid 8947**（next dev，3000 端口，hot-reload 自动生效；
  T-24 不动前端无需关心；既有第五波前端改动（admin metrics 页 + cost panel +
  UserEventsListener 全局 toast）已 hot-reload）

**v1 收口后必做**：

```bash
# 1. 停旧 backend（pid 30876）
kill 30876

# 2. 跑 alembic（落 5 条迁移：feature_flags + subscriptions.refunded_at +
#               model_calls.tenant_id + backfill + team_members.role + backfill）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m alembic upgrade head   # → d4e5f6a7b8c9

# 3. 启新 backend（不带 --reload）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. 验证（应看到 125 routes，含 cost 三端点 / pipelines/user-events SSE /
#         publish-events 带 id: 行 / admin_flags 含 /me + /tenants）
.venv/bin/python -c "from app.main import app; print(len(app.routes))"

# 5. RBAC 验证：用 demo@example.com 登录访问 /app/admin/feature-flags 看入口
#               psql 验证：SELECT user_id, role FROM team_members WHERE role='admin'
#               应看到所有 workspace owner 自动是 admin

# 6. 可选：配 SMTP 真发月账单 / 配 STRIPE / GOOGLE 跑 T-20 真账号 e2e
#    SMTP：.env 加 SMTP_HOST / SMTP_USER / SMTP_PASSWORD + INVOICE_EMAIL_ENABLED=true
#    Stripe + YouTube：见第 7 节 T-20 操作指南
```

**重要**：用户自己重启 backend 时记得 `cd /Users/zhaoguangyuan/project/empty/fliki-clone-api &&
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`（不带 `--reload`），
我前几次会话踩过的坑（cwd / reload / sandbox proxy 注入）都还在第 4 节的「已知限制」里。

---

> 2026-05-04 23:30 更新：**EditAgent v5 字幕按 aspect 重排已落地**。
> - 新增 `ASPECT_SUBTITLE_STYLE` 表：9:16 / 4:5 / 1:1 / 16:9 / 4:3 各自有
>   `font_size` / `margin_v` / `outline` / `shadow`。9:16 用 44/220/3（避开 TikTok 底部 UI），
>   4:5 用 36/180/3（避开 IG 点赞区），16:9 沿用 v4 的 24/72/2 基线。
> - 新增 `build_subtitle_force_style(aspect, *, font_name, scale=1.0)`：返回
>   `(force_style_str, debug_dict)`；scale clamp 到 [0.5, 2.0]，brief 可选 `subtitle_scale`
>   整体缩放（应用场景：投屏 / 老人版字幕加大）。
> - `mux_video_with_audio` 把写死的 `Fontsize=24,MarginV=72,...` 替换成调用
>   `build_subtitle_force_style(target_aspect, scale=subtitle_scale)`；新增
>   `subtitle_scale: float = 1.0` 参数。
> - EditAgent v5：`_produce_one_aspect` 把 `subtitle_style` debug 字段挂到 outputs，
>   即使最终降级到无字幕也算出来给前端展示；新增 `_resolve_subtitle_scale(brief)`
>   读 `brief.subtitle_scale`。
> - 前端 EditArtifact：新增 `SubtitleStyleHint` 横条（仅烧录字幕场景显示，sky 主题）
>   + `<AspectTabs>` 每个 tab 加 hover title「字号 X · MarginV Y · Outline Z · scale ×N」；
>   subtitle_style 从 outputs_json 旁路读，不依赖 renders 表迁移。
> - 单元测试：5 个 aspect force_style 字符串正确；scale 0.5/1.0/2.0/3.0(clamp)/-1/0
>   全部正确兜底；`_resolve_subtitle_scale` 兜底各种垃圾输入到 1.0。
>
> 2026-05-04 23:00 更新：**shots 数据已切到新 API + video step 卡片补齐**。
> - 新增 `useRunShotList` hook（拉 `/api/production/runs/{id}/shot-list` + reload；
>   监听 art / video step state 变化时自动重拉）
> - art 卡片 shots 网格优先读 shotList.shots，缺失 fallback 到 outputs_json.shots
> - **新增 VideoArtifact**（`agent_type === "video"` 之前完全没卡片，
>   只能在 step header 看 state）：每镜 `<video>` 缩略图 + keyframe 作 poster +
>   provider/mode/cost/error；视频还没出但 keyframe 已有时显示「等待视频生成」叠加；
>   头部摘要「N 镜 · X 成功 · Y 失败 · cost $Z」
> - 新增 `<ShotsSourceBadge>`：emerald「shot_lists 表」/ amber「outputs_json」
>   双数据源标识，方便观察是否切到了新表（fallback 用于兼容旧 run / persist 未触发的场景）
> - 后端 sanity 核：用 `persist_step_outputs` 模拟 script→art→video 三轮 persist 后，
>   `GET /production/runs/{id}/shot-list` 返回完整 ShotListOut JSON，与前端 TS 类型 100% 对齐
>
> 2026-05-04 22:30 更新：**VoiceAgent v3 行级细切 + OpenAI Whisper 接入点已落地**。
> - VoiceAgent v3：在 v2「按真实音频时长重切」基础上，每个 shot 的 narration 按
>   标点（`。！？` 主切 + `，；、,;` 兜底 + `max_chars` 兜底 hard-wrap）切成多条，
>   每条按字符占比再分时间。短碎片（< 0.4×max_chars）自动合并到下一行避免「一字一条」。
> - brief 可选 `subtitle_max_chars`（默认 20，clamp 到 [8, 60]）。
> - outputs 新字段：`subtitle_granularity` (`line` / `shot` / `merged`) /
>   `subtitle_lines_per_shot` / `subtitle_max_chars`；subtitles 每条带 `shot_index`。
> - 烟测：3 镜（中间 shot 含 3 句）→ TTS 真长 13.248s → v3 切成 5 条字幕（v2 同 brief 是 3 条），
>   shot2 细切到 3 条；每条 1.1-3.13s，符合阅读节奏。
> - 新增 **OpenAIWhisperProvider**（`app/services/model_gateway/providers/openai_whisper.py`）：
>   显式带 `timestamp_granularities[]=segment+word`；用户在 `.env` 配 `OPENAI_API_KEY`
>   即自动切到 whisper-1 拿真 word/segment 时间戳。gateway ASR 路由改为
>   `[OPENAI, SILICONFLOW]`：有 key 时走 OpenAI，无 key 自动 fallback 到 SF SenseVoice
>   + ffprobe 兜底（实测路由切换正确）。cost 表加 `(OPENAI, ASR) = $0.006/min`。
> - 前端 voice 卡片：sky 徽标「行级 v3 · N/M/K条」/ 「镜级 v2」 / 「v1 兜底」+ 字幕条
>   左侧 `S{shot_index}` 角标 + 预览上限 12 → 18，多余显示「…还有 N 条」。
>
> 2026-05-04 22:00 更新：**VoiceAgent v2 字幕对齐已落地**。
> - 新增 `SiliconFlowASRProvider`（OpenAI 兼容 `/audio/transcriptions`，默认
>   `FunAudioLLM/SenseVoiceSmall`）；gateway 注册 + ASR 路由 + cost 单价 ($0.001/min)
> - 新增 `media.probe_audio_duration_bytes`（ffprobe 从 audio bytes 拿真实时长，
>   作为 ASR 不返 duration 时的兜底——SenseVoice 实测就是这种情况）
> - VoiceAgent 重写为 v2：TTS → ASR → 优先 ASR.duration → 缺失走 ffprobe →
>   按各 shot.narration 字符占比把真实 audio_duration 分配给每条字幕
> - 字幕条仍是 shot-level（不重新分句），但 start/end 用真实音频时长重切，
>   解决 EditAgent v4 循环视频字幕跟旁白对不上的根因
> - outputs 新字段：`audio_duration_s` / `aligned` / `alignment_source`
>   (`asr` / `ffprobe` / `shots_duration`) / `asr_provider` / `asr_model` /
>   `asr_duration_ms` / `asr_segments_count` / `align_warning`
> - persist 新写 metric：`voice_audio_duration_s` / `voice_subtitles_aligned` /
>   `voice_asr_duration_ms` / `voice_asr_segments_count`
> - 前端 voice 卡片：emerald「字幕已对齐 ✓ (asr/ffprobe)」/ amber「字幕未对齐（v1 均分）」
>   徽标 + ASR provider/model/耗时/segments + 偏差秒数
> - 烟测：50 字 narration → TTS 真长 8.928s（v1 会算成 12.0s，差 3.07s）
>   → v2 字幕末端 = 8.928s 完美对齐；alignment_source=ffprobe（SenseVoice 不返 duration）
>
> 2026-05-04 21:00 **DLQ 前端列表 panel 已落地**。pipeline 页面 ProductionPanel 之后挂
> `<DeadLetterPanel>`：status filter（pending/retried/discarded/all）+「仅当前 run」开关 + 30s
> 静默 polling + 行内 retry / discard（pending only，对应后端 400 兜底）+ 折叠 traceback / args /
> kwargs。pending 数 > 0 时即使切到其他 filter 也有 amber 提示徽标。
>
> 2026-05-04 20:30 **Celery 死信队列已落地**。新表 `dead_letter_tasks`（alembic head
> `e58c4a1d2b73`）；celery 模式走 `DLQAwareTask.on_failure` 入库，BackgroundTasks 模式
> 走 `runner.tick` 兜底入库。新增 `routers/dlq.py` 提供 list / retry / discard。
> 6 场景烟测全过：push 入库 + 软去重 attempt++ + retry 走 dispatcher + 已 retried 项再 retry 返 400。
>
> 2026-05-04 20:00 前端切新 API：EditArtifact 优先读 `useRunRenders(runId)`（renders 表 = 权威源），
> outputs_json 仅作 fallback；pipeline 页加「版本 & 发布」panel（versions / publish_plans CRUD）。
>
> 2026-05-04 19:30 数据模型扩展 v1：新增 7 张生产元数据表（alembic head `a4d72b91e3c5`）+ 一次性
> backfill + Agent 通过 runner 的 persist hook 双写到新表（outputs_json 仍写作为 SSE 快照）+ 新增
> `routers/production.py` 暴露查询端点。
>
> 2026-05-04 19:30 ADR-002：`docs/adr/002-agent-orchestration.md` 落地，明确**不引入 LangChain / LangGraph**
> 作为编排层；写明 4 条触发条件 + 4 条「不做什么」。单 Agent 内部仍可自由用任何工具。
>
> 2026-05-04 19:00 EditAgent v4：支持按旁白时长循环视频 + 按 `style_board.aspect_ratio`
> 多比例导出（cover/contain）。`brief.export_aspects` 触发；缺省仅出主比例 = v3 行为。
>
> 2026-05-04 18:55 SSE：前端 polling 已被 EventSource 替换；onerror 自动 fallback 到 polling。

---

## 1. 项目当前形态（30 秒掌握）

`fliki-clone` 已经从「场景化 TTS + 模板成片」升级为**多 Agent 视频生产流水线**：

```
Brief
 └─→ ResearchAgent (LLM 选题)                  ─┐
      └─→ ScriptAgent (LLM 脚本+分镜)[审批] ───┼─→ ArtAgent (LLM prompt 增强 + 关键帧 Kolors)
                                                 ├─→ VoiceAgent (TTS CosyVoice + 字幕)
                                                 └─→ VideoAgent (Kling i2v / GENERATE_VIDEO)[审批]
                                                       └─→ EditAgent (concat + mux + 字幕硬烧)
                                                             └─→ ReviewAgent (静态规则)
```

人保留：选题判断、审美、终审。Agent 接管：研究、脚本、分镜、关键帧、镜头、配音、字幕、粗剪、质检。

---

## 2. 已落地（Phase 0 → Phase 2 大半）

### 2.1 数据模型 / 迁移
| 表 | 用途 | 引入 head |
|---|---|---|
| `model_calls` | 每次外部模型调用的账单（provider/model/action/cost/duration/status） | `7f51c2a48e10` |
| `pipeline_runs` | 流水线运行根（含 `cost_estimated_usd` / `cost_actual_usd` / `cost_reserved_usd`） | `9a6e4d127b58` + `c1e8d3b2f0a9` |
| `pipeline_steps` | DAG 节点（state / attempt / requires_review / outputs_json） | `9a6e4d127b58` |
| `model_quotas` | user 级月度配额（limit / usage / period_start / concurrent_max） | `c1e8d3b2f0a9` |
| **`shot_lists`** | 一个 run 一个分镜表（title/hook/script/cta/topic/style_board/character_cards/aspect） | `a4d72b91e3c5` |
| **`shots`** | 每个分镜一行；script/art/video 三次 persist 按 `(run_id, index)` 自然键合并到同行 | 同上 |
| **`renders`** | EditAgent v4 每个 aspect 一行成片；`(run_id, aspect)` partial unique where is_primary=true | 同上 |
| **`reviews`** | ReviewAgent 每条 issue 一行（severity/area/message/meta_json） | 同上 |
| **`publish_plans`** | 发布计划（platform/status/scheduled_at/external_id/title/description/tags/cover） | 同上 |
| **`metrics`** | 指标时间序列（kind/value_num/value_text/unit/captured_at），voice 已写两条 | 同上 |
| **`versions`** | run 快照标签（label/primary_render_id/is_published 互斥）；便于版本切换/发布 | 同上 |
| **`dead_letter_tasks`** | celery / BackgroundTasks 抛到 task 层的兜底；含 args/error/traceback/attempt_count/status (pending/retried/discarded) | `e58c4a1d2b73` |
| **`tenant_quotas`** | 配额 v2：(tenant_id) 主键的月度配额（plan-derived limit / concurrent_max / display_name）；router/runner 已切到这里，v1 `model_quotas` 仅作兼容 | `c2f9b7a04ef1` |
| **`provider_concurrency_buckets`** | (tenant_id, provider_name) 唯一；acquire/release 由 gateway.run() 自动维护；plan 升级时自动 bump max_concurrent | 同上 |
| **`pipeline_runs.tenant_id`** | run 级的 tenant 命名空间；终态退还走它而非 user_id | 同上 |
| **`platform_credentials`** | 发布执行器 v1：(user_id, platform) 唯一；存 access/refresh token + scope + expires_at；**Track-01 已套 Fernet 加密**（KEY 缺失时降级 plain text + warning） | `8b1f6c2d4a93` |
| **`publish_plans.confirm_real_publish`** | bool 列，default false；Track-02 把 v1 隐藏在 meta_json 的安全闸门提出来；adapter 直接读，前端 PlanRow toggle | **`9c2d4e5f6a7b`** ← head |

### 2.2 Model Gateway（`app/services/model_gateway/`）
- 统一类型 `ModelAction` / `ProviderName` / `RenderRequest` / `RenderResult` / `CallStatus`
- `Gateway.select_provider`：**同 ProviderName 下多 capability provider 并存**（修复了 LLM 被视频 provider 覆盖的 bug）
- 5 个 Provider：
  - `OpenAICompatLLMProvider`（DeepSeek-V3 via SiliconFlow，json_array 用括号计数 + ```围栏``` 容忍解析）
  - `KlingProvider`（GENERATE_VIDEO + IMAGE_TO_VIDEO，含 negative_prompt）
  - `SiliconFlowVideoProvider`（Wan 系列）
  - `SiliconFlowTTSProvider`（`/audio/speech`，自动 fallback `FunAudioLLM/CosyVoice2-0.5B`）
  - `SiliconFlowImageProvider`（`/images/generations`，按 aspect 自动推断 image_size，自动 fallback `Kwai-Kolors/Kolors`）
- `record_call` 同步写 `model_calls`（每次调用都记账，包括 FAILED / DEGRADED）

### 2.3 Pipeline 编排（`app/services/pipeline/`）
- 7 个 Agent：`ResearchAgent` / `ScriptAgent` / `ArtAgent` / `VoiceAgent` / `VideoAgent` / `EditAgent` / `ReviewAgent`
- 3 个模板：`script_only` / `video_demo` / `video_full`（research → script[审批] → art ∥ voice → video[审批] → edit → review）
- `runner.py`：`start_run` / `tick` / `execute_step` / `rerun_step` / `_settle_run_state`（终态首次进入时累加 actual_cost + 退还差额）
- **配额闭环**：`cost.estimate_pipeline_cost(graph, brief)` → `quota.reserve(user, total)` → start_run → 终态 `quota.release(user, reserved-actual)`；cancel 也走同路径
- **Celery 队列分级**（`celery_app.py` + `tasks.py`）：
  - 队列 `interactive` / `media` / `default`，按 `agent_type` 路由
  - `pipeline.tick`（调度）、`pipeline.execute_step`（worker 执行 + 链式触发下一轮 tick）
  - `task_acks_late=True`、`worker_prefetch_multiplier=1` 长任务安全
  - `_schedule_tick(run_id, bg)` 双模式 dispatcher：`celery_enabled=true` → `tick_task.delay`，否则 → `BackgroundTasks`
- **Media 工具**（`app/services/media/`）：
  - `concat_video_segments(urls)`：流复制 → libx264 重编码两层降级
  - `mux_video_with_audio(video, audio, srt_path=None)`：一次 ffmpeg 同时混音 + 字幕硬烧；自动选 CJK 字体（macOS Hiragino Sans GB / Linux Noto Sans CJK SC）；用 ffprobe + `-t min(video,audio)` 绕过 ffmpeg 6.0 mp3+libx264 `-shortest` 丢音轨的 bug
  - `subtitles_to_srt(subs)` + `upload_srt(text)`
  - `extract_last_frame(url)` / `split_to_sub_segments`

### 2.4 API（`app/routers/pipelines.py`）
| 端点 | 用途 |
|---|---|
| `POST /api/pipelines` | 启动（自动估值 → 配额校验 → 预扣 → 启动；402/429 拦截额度/并发不足） |
| `POST /api/pipelines/estimate` | 仅估值不启动 |
| `GET /api/pipelines/quota` | 查 user 当前 quota |
| `GET /api/pipelines/{id}` | run 详情（仍保留，作为 polling fallback / 手动刷新） |
| **`GET /api/pipelines/{id}/events`** | **SSE 流：snapshot → step_state / run_state；终态后服务端关闭** |
| `POST /api/pipelines/{id}/tick` | 强制推进一步 |
| `POST /api/pipelines/{id}/steps/{name}/rerun` | 单步重跑 |
| `POST /api/pipelines/{id}/steps/{name}/approve` | 通过审批（事件单独广播 step + run，因为不走 runner） |
| `POST /api/pipelines/{id}/cancel` | 取消（自动退还 reserved-actual；广播 run + 所有 cancelled step） |

**生产元数据查询路由**（`app/routers/production.py`，前缀 `/api/production`）：

| 端点 | 用途 |
|---|---|
| `GET /production/runs/{id}/shot-list` | 拉 shot_list + 嵌套所有 shots（含 art/video 字段合并后状态） |
| `GET /production/runs/{id}/renders` / `GET /production/files/{id}/renders` | 多比例成片列表（is_primary=true 排第一） |
| `GET /production/runs/{id}/reviews` | issues 按 error→warning→info 排序 |
| `GET /production/runs/{id}/metrics?kind=` | 指标时间序列；voice 已写 char_count / subtitles_duration_s |
| `GET /production/files/{id}/publish-plans` + `POST/PATCH/DELETE /production/publish-plans/{id}` | 发布计划 CRUD |
| `GET /production/files/{id}/versions` + `POST /production/versions` + `POST /production/versions/{id}/publish` + `DELETE` | 版本快照标签 + 互斥 published 切换 |

**死信队列路由**（`app/routers/dlq.py`，前缀 `/api/dlq`）：

| 端点 | 用途 |
|---|---|
| `GET /dlq?status=&run_id=&limit=` | 列本人 DLQ；按 status / run_id 可选过滤 |
| `GET /dlq/{id}` | 详情含 traceback |
| `POST /dlq/{id}/retry` | 仅 pending 可重投；走 `_retry_dispatch`（celery 或 BackgroundTasks）；标 retried |
| `POST /dlq/{id}/discard` | 仅 pending 可丢弃；body 可附 notes |

**SSE 协议**（`event:` 字段）：
- `snapshot` — 连接首条；data 是完整 RunOut（含 steps）
- `step_state` — 单步变化；data 是 StepOut + run_id
- `run_state` — 顶层变化；data 是 RunOut 去掉 steps（前端合并保留 steps）
- `: ping`（注释行）— 25s 心跳，浏览器自动忽略

**事件总线**：`app/services/pipeline/events.py`
- `publish(run_id, event_type, payload)`：sync，runner / celery worker / 路由共用；redis 不可用仅 warning
- `subscribe(run_id, *, stop_event)`：async，idle 时 `yield None` 让 SSE 端循环检查断连/心跳，避免 `wait_for(__anext__)` 取消正在进行的 `pubsub.get_message`
- redis 频道 `pipeline:run:{run_id}`，envelope `{"type": ..., "data": ...}`

### 2.5 前端（`fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx`）
- 模板下拉（`script_only` / `video_demo` / `video_full`）
- Brief JSON 编辑 + 350ms 防抖自动调 `/estimate`
- 4 格 stat：本次预估 / 本次预扣 / 实际花费 / 本月剩余配额；月度 usage / limit + 并发使用率；每步预估明细折叠
- 启动按钮闸门：估算 > 剩余 / 并发到上限时禁用 + amber 文案；按钮文案带预估金额「启动（预估 $X）」
- **SSE 流式更新**（`src/hooks/use-pipeline-stream.ts`）：
  - `usePipelineStream({ runId, enabled, onUpdate })`：原生 `EventSource(url, {withCredentials: true})`；snapshot → 全量 setRun；step_state → 按 id upsert 到 `prev.steps`；run_state → 顶层合并保留 steps
  - 连续 2 次 onerror → fallback 到 2.5s polling（保留旧行为，UI 不黑屏）
  - run 终态 hook 自动 close + onTerminal callback
  - 「流水线节点」标题旁加 `StreamModeBadge`：emerald「实时」/ amber dot 闪烁「轮询」
- 各 agent_type 专属预览：
  - `art` → 风格板 + 角色卡 + **关键帧缩略图网格**（每镜 1 张，失败镜 amber `✕`）
  - `voice` → `<audio>` 旁白 + 字幕轨折叠
  - `edit` → `<video>` 成片 + **状态徽标**（"字幕已烧录 ✓" / "已混音 ✓" / "未混音" / "视频已循环 ↻"）+ `.srt` 下载链接 + 多比例 tab + **数据源徽标**（"renders 表" emerald = 权威源 / "outputs_json" amber = 兼容期）
  - `review` → 按 severity 高亮 issues
- 单步重跑、审批、取消按钮
- **`<ProductionPanel>`**（pipeline 页面下方，仅 fileId 非空时显示）：
  - 「版本」列：`listFileVersions` + 「另存为版本」表单（label/notes/primary_render 下拉/is_published 互斥）+ 行内置顶 + 删除（`useRunRenders(currentRunId)` 提供 render 下拉源）
  - 「发布计划」列：`listFilePublishPlans` + 「新建发布计划」表单（platform/render/scheduled_at/title）+ 行内 status 下拉 + 标记 published 快捷 + 删除
  - 「刷新」按钮 + delete 前 confirm

---

## 3. 当前状态 / 实际能力

| 能力 | 是否可跑 | 备注 |
|---|---|---|
| `script_only` 端到端 | ✅ | LLM only，~25s，$0.006 |
| `video_full` 端到端 | ✅ | research+script+art+voice+video+edit+review；视频耗时 1-2 min/镜 |
| 关键帧 → IMAGE_TO_VIDEO 一致性 | ✅ | art 出 keyframe，VideoAgent 自动切 i2v 模式 |
| 字幕硬烧（中文） | ✅ | Hiragino Sans GB 渲染清晰，无豆腐块 |
| 旁白混音 | ✅ | mux 替换音轨 + ffprobe `-t` 绕 `-shortest` bug |
| 月度配额预扣 + 终态退还 | ✅ | 402 拦截额度不足 / 429 拦截并发 |
| Celery 异步队列（worker 模式） | ✅ | dispatch 路径已验证消息入 redis |
| 重启浏览器 run 恢复 | ✅ | 状态全在 DB，刷新页面 SSE snapshot 自动对齐 |
| SSE 流式状态推送 | ✅ | `GET /pipelines/{id}/events`；snapshot + step_state + run_state；终态自动断开；EventSource 异常退到 polling |
| EditAgent v4：按旁白循环 + 多比例 | ✅ | `audio_dur > video_dur` 时 `-stream_loop -1 + -t audio_dur` 让视频循环；`brief.export_aspects` 触发多比例（默认仅主比例）；前端 `previews_by_aspect` 切换 tab |
| VoiceAgent v2：字幕对齐真实音频 | ✅ | TTS → ASR (SenseVoiceSmall) → ffprobe 兜底 → 按字符比例把字幕末端对齐到真实 audio_duration（v1 是按 shots.duration_s 之和均分，循环视频里漂）；前端「字幕已对齐 ✓ (ffprobe/asr)」徽标 + 偏差秒数 |
| VoiceAgent v3：行级细切 + Whisper 接入点 | ✅ | v2 之上每镜按 `。！？` 主切 + `，；、` 兜底切成多行，每行按字符占比再分时间；新增 `OpenAIWhisperProvider`（gateway ASR 路由 `[OPENAI, SILICONFLOW]`，配 `OPENAI_API_KEY` 自动切 whisper-1 拿 word-level）；前端「行级 v3」徽标 + `S{shot_index}` 角标 |
| 前端 art / video 卡片切到 shot-list 新 API | ✅ | art shots 网格优先读 `shot_lists.shots`（缺失 fallback outputs_json）；video step 之前没卡片，新增 `VideoArtifact` 每镜 `<video>` + keyframe 作 poster + provider/cost/error；`<ShotsSourceBadge>` emerald「shot_lists 表」/ amber「outputs_json」 |
| EditAgent v5：字幕按 aspect 重排 | ✅ | `ASPECT_SUBTITLE_STYLE` 表（9:16 字号 44/MarginV 220 vs 16:9 字号 24/MarginV 72）+ `build_subtitle_force_style` + brief.subtitle_scale 整体缩放 [0.5, 2.0]；前端 `SubtitleStyleHint` 横条 + `<AspectTabs>` hover 提示 |
| 生产元数据 7 表 + persist 双写 | ✅ | step 完成后 runner 钩子自动写新表；新表可被 `/api/production/*` 端点查询 |
| 前端切到 /production 新 API | ✅ | EditArtifact 优先读 useRunRenders（权威源）+ outputs_json fallback + 数据源徽标；pipeline 页加 ProductionPanel（versions / publish_plans CRUD） |
| Celery 死信队列 + 路由 + 前端 panel | ✅ | `dead_letter_tasks` 表；celery 模式 `DLQAwareTask.on_failure` 自动入库；BackgroundTasks 模式 `runner.tick` 兜底；`/api/dlq` list / retry / discard；pipeline 页面 `<DeadLetterPanel>`：status filter + 仅当前 run + 30s polling + retry/discard + 折叠 traceback/args/kwargs |
| **配额 v2 tenant 级分桶** | ✅ | `tenant_quotas` + `provider_concurrency_buckets` + `pipeline_runs.tenant_id`；`resolve_tenant_id`：`ws:{workspace.id}` > `u:{user_id}` > `anon:default`；plan 派生 monthly/concurrent/per-provider max；`gateway.run()` 入口 acquire/release（缺 tenant_id 自动 user_id 兜底）；桶满返 `CallStatus.RATE_LIMITED` 不计费；`runner._settle_run_state` 走 `release_tenant`；前端 4 格 stat 下加 tenant 徽标 + 折叠 Provider 并发桶 utilization bar；端到端 + 6 个烟测 PASS |
| **VoiceAgent v4 word-level 强对齐** | ✅ | OpenAI Whisper-1 返 `words` 时进入 v4：`_build_subtitles_v4_word_aligned` 按字符比例做 origin↔asr 文本映射，每条 line 的 start/end 用真实 word timestamp；line.words 给前端做卡拉 OK 高亮；健康检查降级（words 太少 / 字符比例严重失调 → 退 v3）；前端 violet「word v4」徽标 + 字幕条 word 时间轴卡片；6 个烟测 PASS。**激活**：`.env` 配 `OPENAI_API_KEY`，无 key 时 v3 行级继续工作 |
| **ArtAgent v3 角色一致性** | ✅ | 双层方案：(1) `_generate_character_anchor` 单独出主角 1:1 参考板（`outputs.character_anchor.url`，未来给 IP-Adapter 用）；(2) `_inject_consistency_into_shots` 把 `[Consistent character: protagonist=...; appearance=...; wardrobe=...]` 强制注入每镜 `enhanced_prompt`，`negative_prompt` 追加防漂关键词；`brief.character_consistency`：`auto`/`prompt-only`/`anchor`/`off`；`brief.protagonist_role` 显式选主角；锚点失败 mode=anchor 自动降到 prompt-only；前端 v3 徽标 + 锚点缩略图 panel + shots 网格 🔒 角标；8 个烟测 PASS |
| **发布执行器 v1（dry-run / youtube / bilibili）** | ✅ | `app/services/publishing/`：adapter 协议 + dry-run（始终启用，回 mock external_id）/ youtube（真发，需 GOOGLE_CLIENT_ID + OAuth + 安全闸门 `plan.meta.confirm_real_publish=true`）/ bilibili（stub，引导手动上传）+ executor + credentials + oauth helpers；`POST /api/production/publish-plans/{id}/execute` 调入；`GET/DELETE /api/production/platforms/credentials`；`POST /api/production/platforms/{p}/oauth/start` + `GET /api/production/platforms/{p}/oauth/callback`（YouTube）；系统级异常（PublishError）入 DLQ + 502；幂等性：已 `published` 的 plan 拒绝重发；前端 PlanRow 加 Upload 按钮 + plan.error 显示 + external_id；新 `<PlatformCredentialsPanel>`（real/stub 徽标 + 绑定/撤销按钮）；4 场景端到端 PASS |
| **publish 任务异步化（celery + SSE）** | ✅ | Track-03：`POST /publish-plans/{id}/execute` 默认返 **202 + dispatcher + events_url + Location 头**（`?sync=true` 兼容兜底走 v1 同步路径）；celery task `publish.execute_plan`（queue=default，`acks_late=True`），BackgroundTasks fallback 共用同一 task body 函数保证 SSE 事件流语义一致；新 SSE 端点 `GET /publish-plans/{id}/events`：`event: snapshot` + `event: publish_plan_state phase=running\|completed\|system_error` + 25s `: ping` 心跳；`events.py` 抽出 `_publish_to_channel` / `_subscribe_channel` 内核让 `publish:plan:{id}` 与 `pipeline:run:{id}` 复用同一份 redis pub/sub；前端新 hook `use-publish-plan-stream.ts`（EventSource + 2 次 onerror fallback 2.5s polling），PlanRow 行内 stream/poll 徽标 + `<Loader2 spin>` + 终态 toast；4 路径函数级 + 1 路径队列级烟测 PASS（HTTP TestClient 因 sandbox event loop 没跑，留给真启 backend 后人工 curl）|
| **YouTube chunked PUT + 进度回写 SSE** | ✅ | Track-13：YouTube adapter 删 v1 multipart 一把发；改成 8 MiB 分片 chunked PUT（`_initiate_resumable_upload` 拿 session uri → `_chunked_put` 切片 + Content-Range 滚动 + 308/200/201 状态机）；单片 5xx/408/429 指数退避重试 1s/2s/4s 最多 3 次，4xx 立即抛 `PublishError`；每完成一片 `progress_cb({phase, bytes_uploaded, total, percent, chunk_index, chunk_count})` → executor `_make_progress_cb` 闭包 read-modify-write `publish_plans.meta_json.upload_progress`（PG `JSON` 列不是 `JSONB` 必须读改写）+ `publish_plan_event(plan_id, "upload_progress", info)` 推 SSE；前端 `use-publish-plan-stream.ts` `addEventListener("upload_progress")` + `<UploadProgressBar>`（下载阶段灰 / 上传阶段 sky）；下载阶段 start/complete 也回调让前端不卡 0%；8 case 协议层 mock 单测 PASS |
| **DLQ retry 按 task_name 路由** | ✅ | Track-15：`routers/dlq.py::_retry_dispatch` 识别 `task_name="publish.execute_plan"` 改派 `execute_publish_plan_task.apply_async`（celery 模式）/ `BackgroundTasks.add_task(_publish_execute_with_events, ...)`（BG fallback）；其它 task_name 仍走既有 `tick_task` 路径；顺手修隐藏 bug：旧版 router 入口 `if not run_id: 400` 让 publish DLQ 死信无法 retry（publish_plans 与 pipeline_runs 没外键，task 没 run_id）；改成 `task_name="publish.execute_plan"` 时不要求 run_id；7 case 单测覆盖 |
| **Admin Feature Flags UI** | ✅ | Track-14：后端 `routers/admin_flags.py` 抽 `_is_admin_email`；新加 `GET /api/admin/feature-flags/me`（任何登录用户可调返 `{is_admin, email}` 让前端探测是否渲 admin 入口而不抛 403）+ `GET /tenants`（admin 限定，按 tenant_id 聚合 SELECT + flag_count）；前端新 `app/admin/feature-flags/page.tsx`（968 行）顶部 tenant 选择器 + 表格列 flag_name + value（pct 滑块 / toggle / variant 下拉自适应）+ updated_at + Apply + Delete + 「新增 flag」dialog 从 known_flags 选 + toast；`lib/admin-flags.ts` 5 端点 fetch helper；`sidebar.tsx` mount 时 fetch /me admin 命中渲入口；7 case 单测 |
| **Stripe webhook charge.refunded + 6 case 单测** | ✅ | Track-16：alembic head `a1b2c3d4e5f6` → `b2c3d4e5f6a7`，加 `subscriptions.refunded_at TIMESTAMPTZ NULL`（不加 server_default 避免老行误打标 / 不加索引退款查询频次极低 / downgrade `drop_column` 无副作用）；`webhook_handlers.py` 加 `_handle_charge_refunded(charge, *, event_id)`：`metadata.subscription_id` 优先 → `customer` 反查最新订阅；都不命中返 `{handled: True, matched: 0, reason: ...}` 让 stripe 不重投；**只打标 refunded_at**，不动 `tenant_quotas` / `users.plan` / `subscriptions.plan`（v1 用户体验优先；ops 评估后人手降级）；6 case 端到端覆盖 5 类 stripe 事件 + unknown |
| **SSE 断网重连 last_event_id 续传** | ✅ | Track-17：`services/pipeline/events.py` 升级为 redis Stream + pub/sub 双写：`_publish_to_channel` 加 `XADD {channel}:stream * data <json>`（MAXLEN ~1000 approximate trim）+ `PUBLISH {channel}` 保留兼容；`_subscribe_channel` 改用 `xread({stream: cursor}, block=1000)`，`cursor=last_event_id or "$"`；yield 升级为 3-tuple `(event_type, payload, entry_id)`；`subscribe` / `subscribe_publish_plan` 加 `last_event_id` 透传；XADD 失败不阻塞 PUBLISH；redis 不可用 noop；`routers/{pipelines,production}.py::_sse_format(event, data, event_id=None)` 非空时 emit `id: <event_id>\n` 在 `event:` 之前；两个 SSE 端点从 `request.headers.get("Last-Event-ID")` 透传到 subscribe；浏览器原生 EventSource 自动带 `Last-Event-ID` 头不用前端改；10 case 单测 + 3 case 真连 redis 烟测 |
| **model_calls 加 tenant_id + 按 tenant 聚合 cost 视图** | ✅ | Track-18：alembic head `b2c3d4e5f6a7` → `c3d4e5f6a7b8`，加 `model_calls.tenant_id VARCHAR(200) NULL` + `ix_model_calls_tenant_id` 索引 + 一次性 backfill 老行为 `'u:' \|\| user_id`（与 `pipeline.tenant.resolve_tenant_id` 兜底约定一致）；`services/model_gateway/cost.py::record_call` 加 `tenant_id` kwarg + `_resolve_tenant_for_record(explicit, user_id)` 公共判定（explicit > `u:{user_id}` > None）；`gateway._record` 透传 `request.tenant_id`；新 `routers/cost.py` 2 端点：`GET /api/cost/summary?tenant_id=&period=monthly\|weekly\|daily` 按 provider 聚合（cost_usd / call_count / success_count / failed_count）+ `GET /api/cost/recent?tenant_id=&limit=`；`_resolve_query_tenant` 安全 helper：未传 → user 自己 / 传了 → 仅 admin 直通否则静默覆盖回自己；前端 `lib/cost.ts` + `pipeline/page.tsx::CostBreakdownPanel` 按 provider 横向 bar 颜色映射（emerald=OpenAI / sky=SiliconFlow / amber=Kling / violet=ElevenLabs / slate=local），与 `refreshQuota` 同生命周期；10 case 单测（4 unit + 6 integration） |
| **metric dashboard（cost 时序图 + admin metrics 页）** | ✅ | Track-21：`routers/cost.py` 末尾追加 `GET /api/cost/timeseries?tenant_id=&provider=&period=daily\|weekly&days=30`：`DATE_TRUNC('day'/'week', created_at)` GROUP BY day, provider 聚合，返 `[{date, provider, cost_usd, call_count}]`；复用 T-18 `_resolve_query_tenant` 鉴权（admin 邮箱可指定他人）；前端新页 `app/[locale]/(app)/app/admin/metrics/page.tsx` tenant 选择器 + provider 多选 chips + period toggle + recharts LineChart 多 series（每 provider 一条折线）+ 顶部数字 total_cost / total_calls；`lib/cost.ts` 加 `getCostTimeseries`；`sidebar.tsx` admin 渲「Admin · Metrics」入口与 Feature Flags 并列；8 case 单测 |
| **月账单 PDF + SMTP 邮件（invoice.paid）** | ✅ | Track-22：`requirements.txt` 加 `reportlab>=4.0`；`config.py` 加 5 条 `SMTP_*` 字段 + `invoice_email_enabled: bool = False`（缺省关闭防本地误发）；新 `services/billing/invoice_pdf.py` reportlab 渲 A4 PDF 含 plan + period + 按 provider cost 拆分表格 + 总金额（数据源 stripe invoice.lines + T-18 期内 model_calls）；新 `services/email/{__init__,smtp_client}.py` 薄封装 stdlib smtplib（缺 SMTP 抛 EmailNotConfigured；不引第三方依赖）；`webhook_handlers.py` 加 `invoice.paid` dispatch + `_handle_invoice_paid`：`invoice_email_enabled=False` 返 `{handled:True, sent:False, reason:...}` 让 stripe 不重投；与 T-16 既有 5 handler 共存；7 case 单测 |
| **ADMIN_EMAILS 迁回 Settings** | ✅ | Track-23：`config.py` 加 `admin_emails: str = "demo@example.com"` 字段（pydantic-settings 自动从 env 读）；`routers/admin_flags.py::_allowed_admins()` 改读 `get_settings().admin_emails`，逗号 split + strip + lower + 去空 + set 化；保留 `demo@example.com` 兜底（dev fixtures 兼容）；T-10/14/18 既有调用方走 `_is_admin_email` 不变；`tests/test_admin_flags.py` 既有 7 case 用 monkeypatch settings 替代 `os.environ.set` 注入；6 case 新单测 |
| **配额超限 / Provider 桶满 SSE 实时推送** | ✅ | Track-25：`services/pipeline/events.py` 复用 `_publish_to_channel`/`_subscribe_channel` 内核新加 `publish_user_event` + `subscribe_user`，channel `user:{user_id}` 与既有 channel 互斥；继承 T-17 redis Stream + pub/sub 双写 + 断网续传；`quota.reserve_tenant` 抛 402 之前调 `publish_user_event("quota_exceeded", {tenant_id, attempted_cost, monthly_limit, current_usage, deficit_usd})`；`provider_buckets.acquire` BucketFull 调 `publish_user_event("bucket_full", {provider_name, current_in_flight, max_concurrent})`；`gateway.py` 把 user_id 透传给 bucket acquire；新路由 `GET /api/pipelines/user-events` SSE（owner 鉴权 + snapshot+增量）；前端新 `use-user-events.ts` hook + `<UserEventsListener/>` client component 挂在 `(app)/layout.tsx` 全局生效；toast：`feedback.error` quota / `feedback.warning` bucket；10 case 单测 |
| **RBAC v1（workspace member role + 邮箱白名单 fallback）** | ✅ | Track-24：alembic head `c3d4e5f6a7b8` → `d4e5f6a7b8c9`，加 `team_members.role VARCHAR(20) DEFAULT 'editor'` + `ix_team_members_role` 索引 + 一次性 backfill workspace owner 设为 `admin`；新模块 `services/auth/{__init__.py, rbac.py}`：`get_user_role(user_id, workspace_id) -> "admin"\|"editor"\|"viewer"\|None` + `is_admin(user_id, *, workspace_id=None, email=None)` 三路径（explicit workspace → 任意 workspace → 邮箱白名单 fallback）+ 60s 内存缓存（同 `pipeline.tenant.resolve_tenant_id` pattern）；`routers/admin_flags.py::_require_admin` + `routers/cost.py::_resolve_query_tenant` admin 判定切到 `rbac.is_admin(...)`，`_is_admin_email` 保留作 fallback 兜底（不删，dev fixtures `demo@example.com` 仍生效）；前端 `lib/admin-flags.ts::getAdminMe` 返 schema 不变；10 case 单测覆盖三路径 + cache TTL + alembic 列存在 + owner backfill |
| **多角色锁定 v5（ArtAgent + VideoAgent）** | ✅ | Track-09：v3/v4 只锁主角；v5 升级为「每个 character_card 各一份 anchor」+「按 `shot.focus_character` 逐镜选对应 anchor + 注入对应前缀」；`_select_relevant_characters`（主角永远保留；其余角色被 focus 引用才纳入，不浪费 image 调用）→ `_generate_character_anchors`（批量出 anchor，单个失败不影响其它）→ `_inject_consistency_into_shots(characters_by_name=)`；`_generate_keyframes(anchors_by_role=)` 多角色 anchor URL 字典；VideoAgent `_select_ref_image` 按 `shot.locked_character` / `focus_character` 选对应 anchor，返 `(url, source, anchor_role)`；outputs 新增 `character_anchors`/`shots[i].locked_character`/`ref_anchor_role`/`ref_image_summary.by_role`/`character_anchors_by_role`；前端 ArtArtifact 多角色 grid（主角 emerald / 配角 violet 边框）+ shots 网格 🔒 角标按 `locked_character` 着色；VideoArtifact 头部按角色统计 + 每镜 `ref_anchor_role` 角标；`character_anchor` 单字段保留为主角的（向后兼容前端 v3 徽标 / 旧 video.py）；6 case + 既有 31 case 零回归 |
| **canary 灰度 / feature_flags v1** | ✅ | Track-10：新表 `feature_flags(id, tenant_id, flag_name, value_json, created_at, updated_at)` + 唯一约束 `(tenant_id, flag_name)`（alembic `a1b2c3d4e5f6`）；`services/pipeline/feature_flags.py`：`get_flag`/`set_flag`（PG `ON CONFLICT` upsert）/`load_for_tenant`（runner build ctx 时一次性批量）/`is_enabled`；value 形态 `{"pct":0..100}`（hash SHA-1 前 8 hex mod 100，bucket < pct 命中）/`{"enabled":bool}`/`{"variant":"v4"/"v3"/"off"}`；`PipelineContext` 加 `feature_flags`/`tenant_id`/`tenant_plan`；ArtAgent 入口读 `art_ipadapter_pct`：缺省→默认 v4；命中→喂 anchor 走 v4 IP-Adapter；不命中→`anchors_url_by_role={}` 主角镜降到 v3 prompt-only（前缀注入仍生效）；outputs 加 `canary_variant`/`canary_flag_value` 可观测；admin 路由 `GET/PUT/DELETE /api/admin/feature-flags`（邮箱白名单 `ADMIN_EMAILS=...`，fallback `demo@example.com`）；4 case 叠加 multichar 烟测 + service 层 hash 染色稳定性烟测 PASS |
| **Stripe 计费对接 v2 + tenant_quotas 同步** | ✅ | Track-11：6 路由 `/api/billing/{plan,checkout-session,portal-session,checkout(legacy),portal(legacy),webhook}`；`services/billing/`：`stripe_client.py`（薄封装 SDK + `StripeNotConfigured` 翻 503）/`webhook_handlers.py`（4 事件矩阵：`checkout.session.completed` / `customer.subscription.{updated,deleted}` / `invoice.payment_failed`）/`tenant_sync.py`（`sync_user_plan(user_id, new_plan)` 走 `pipeline.tenant.resolve_tenant_id` → `quota.update_tenant_plan`）；`quota.update_tenant_plan(tenant_id, new_plan)` 新加：UPDATE `tenant_quotas.plan` + 升级取 `PLAN_DEFAULTS` bump `monthly_limit_usd`/`concurrent_max`（降级**保留**运维手调过的值）+ 遍历 `provider_concurrency_buckets` 调 `ensure_bucket(plan=new)` 自动 bump per-provider max_concurrent；新前端 `/app/billing` 三栏 plan 卡片（free/standard/premium）+ Active 徽章 + 「升级」跳 Stripe Checkout / 「管理订阅」跳 Customer Portal；`?session_id=` 跳回参数 1.5s 后 refetch；不动 alembic（复用现有 `subscriptions`/`tenant_quotas`/`provider_concurrency_buckets`）；handler dispatch + tenant_sync 单元烟测 PASS（真 Stripe CLI 联调要本地配 `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` 后跑 `stripe trigger checkout.session.completed`）|

---

## 4. 已知限制 / 风险（**别再踩**）

1. **后端启动 cwd 必须是 `fliki-clone-api`**，否则 pydantic-settings 读不到 `.env`，jwt_secret / kling key / siliconflow key 全用 default → token 失效 + provider 调用失败。
   - ❌ `python -m uvicorn ... --app-dir /abs/path/fliki-clone-api`（cwd 是 invocation dir）
   - ✅ `cd fliki-clone-api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
2. **不要带 `--reload`**：本机 reload 会 spawn 出 uv 管的 Python 3.12 子进程（项目 venv 是 3.10）→ `ModuleNotFoundError: No module named 'app'`。改代码后**手动重启**。
3. **SiliconFlow 不时下线模型**（实测 `fish-speech-1.5` / `FLUX.1-schnell` 都已禁用）。`.env` 已切到 `CosyVoice2-0.5B` / `Kolors`；TTS / Image provider 还有自动 fallback 兜底。
4. ~~EditAgent v3 仍用 `-t min(video,audio)` 截短~~ → **v4 已修复**；~~字幕仍按 shots.duration_s 均分~~ → **VoiceAgent v2 已修复**（按真实 audio_duration 重切）；~~每镜单条字幕过长~~ → **VoiceAgent v3 已修复**（按标点切多行）。剩下：多比例共用同一份字幕（不按 aspect 重排版面，留 EditAgent v5），word-level 强对齐 / 卡拉 OK 高亮（需要用户配 `OPENAI_API_KEY` 跑 whisper-1，或将来 v4 引入 faster-whisper 本地化）。
4a. **SiliconFlow SenseVoiceSmall 实测不返回 duration / segments**（即使 `response_format=verbose_json`），所以 v2/v3 实际走 ffprobe 兜底拿真实时长——不影响对齐效果，只是 alignment_source 会显示 `ffprobe` 而非 `asr`。
4b. **要拿 word/segment-level 时间戳**：在 `.env` 配 `OPENAI_API_KEY=sk-...` 即可，gateway ASR 路由会自动切到 `OpenAIWhisperProvider`（whisper-1，$0.006/min；显式带 `timestamp_granularities[]=segment+word`）。当前 v3 没有用 word timings 做强对齐，留给 VoiceAgent v4。
5. **ArtAgent v2 角色一致性会漂**：每镜独立出图，主角形象跨镜不锁定。要 v3 上 IPAdapter / Flux Redux / 角色 LoRA。
6. **partial_failed 不退还配额**：v1 选择，user 必须 cancel 才能拿回额度。
7. **Cancel 不强切断已经在跑的视频生成调用**，只阻止后续 step。
8. **Cursor agent sandbox 里启 celery worker** 会因为 `os.getloadavg()` OSError 让 heartbeat 反复重连（不影响 task 入/出队）。**用户真实 macOS 环境无此问题**。
9. **当前 backend 是同进程 BackgroundTasks 模式**（`CELERY_ENABLED=false` 默认）。视频 step 会占一个进程数分钟。要并发就 `make pipeline-worker` + `.env` 设 `CELERY_ENABLED=true`。

---

## 5. 立即可验证

```bash
# 1. 跑迁移（已 head，重复跑 no-op）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m alembic upgrade head

# 2. 启 backend（注意 cd！）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 启前端
cd /Users/zhaoguangyuan/project/empty/fliki-clone && npm run dev

# 4. 浏览器 http://localhost:3000/zh/app/project/<file-id>/pipeline
#    选 video_full → 看 4 格 stat → 启动 → 审批 script → 审批 video → 看 edit 卡片
```

可选 Celery worker 模式（要起 redis）：
```bash
# 改 .env：CELERY_ENABLED=true
# 起 worker（在另一个终端）：
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && make pipeline-worker
```

---

## 6. 当前活跃后台进程

- **后端 pid 66867**（启于 2026-05-04 23:05；监听 `127.0.0.1:8000`；已加载 VoiceAgent v3 + OpenAI Whisper provider + EditAgent v5 + 前端 art/video/edit 卡片切新 API）
- **前端 task 243452**（pid 35492）：`npm run dev`，`http://localhost:3000`（Next 16 webpack；hook 改动 hot-reload 无需重启）

> 历次旧 backend task 已全部 kill：145111 / 483095 / 643260 / 721693 / 23157 / 35566 / 74188 / 80246。

> 重启 backend 必须 `cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && .venv/bin/python -m uvicorn ...`。
> 用 shell 工具的 `working_directory` 参数**不可靠**（沙盒包装层会让 `import app` 失败）；用 `cd && python` 链式命令最稳。

---

## 7. 下一会话主线推荐顺序（带工作量估计）

第六波合完后剩余路线（**v1 工程闭环全部就绪；剩余都是外部依赖 / 商务问题 / 长尾**）：

| 优先级 | 任务 | 工作量 | 触发条件 / 价值 |
|---|---|---|---|
| ~~★★~~ ✅ 第一+二波 | ~~Voice/Art/Edit/Publish/Quota/Canary/Stripe~~ | ~~10 天~~ | 2026-05-04+05 全 done |
| ~~★★~~ ✅ 第三波 | ~~T-13 / T-14 / T-15 / T-16 / T-17~~ | ~~2.5 天~~ | 2026-05-05 14:30 全 done |
| ~~★~~ ✅ 第四波 | ~~T-18 model_calls tenant_id + cost 视图~~ | ~~半天~~ | 2026-05-05 15:00 done |
| ~~★~~ ✅ 第五波 | ~~T-21 / T-22 / T-23 / T-25~~ | ~~3 天~~ | 2026-05-05 15:50 全 done（120 PASS）|
| ~~★★~~ ✅ 第六波 | ~~T-24 真 RBAC（workspace member role）~~ | ~~1.5 天~~ | **2026-05-05 16:30 done（130 PASS, alembic d4e5f6a7b8c9）** |
| ★★ | **T-20 YouTube + Stripe 真账号 e2e** | 半天（**非代码**）| 链路全通只差用户配真 key + 跑一次：Track-13 chunked PUT + Track-16 webhook + Track-22 invoice 邮件全覆盖；用户配 `.env` 后跑一次 60MB 视频真上传 + 4242 卡 checkout + dashboard refund 一次即可；写 `E2E_VERIFY_REPORT.md` 留档 |
| ★★ | **T-12 bilibili 自动发布**（依赖商务）| 2-3 天 | 等 MCN/合作伙伴入驻拿 OpenAPI；adapter stub 已留好 |
| ★ | **T-19 ArtAgent v6 真 multi-IP**（外部依赖）| 1-1.5 天 | 等 SiliconFlow Kolors-IP / Replicate Flux Redux 上 multi-IP 端点；当前 Track-09 `anchors_by_role` 接入点已留 |
| ★ | **L-04 月账单 PDF + 邮件** | 1 天 | Track-11 follow-up：拿 stripe `invoice.paid` 渲染 PDF + 邮件 |
| ★ | **L-05 真 RBAC（workspace member editor/viewer）** | 1.5 天 | 替换 Track-10/14 邮箱白名单 |
| ★ | **L-13 ADMIN_EMAILS 迁回 Settings** | 0.5 天 | Track-10/14 留的 cleanup（Track-01 互斥锁早已解除） |
| ★ | **L-12 前端 i18n 完整覆盖** | 1.5 天 | 当前 zh/en 部分页面有缺失 |
| ★ | **L-03 metric dashboard（cost / view_count 时序）** | 1.5 天 | 配 T-18 model_calls.tenant_id 一起做能直接出按 tenant 视图 |
| ★ | **L-10 配额超限 SSE 实时推送** | 半天 | 用 Track-17 redis Stream 现成框架推 `quota_exceeded` 事件 |
| ★ | **T-15 follow-up：DLQ retry 端点身份切换** | 1 小时 | retry 当前用调用者 user_id，应该用死信原 user_id（避免 admin 重投覆盖审计身份）|
| ★ | **T-13 follow-up：上传进度 fallback polling** | 1 小时 | SSE 不可用时前端拉 `publish_plans.meta_json.upload_progress` 字段轮询展示 |

> 不建议下次先做：langgraph 整体替换（见 ADR-002）。

---

## 8. 关键文件路径速查

```
fliki-clone-api/
├── docs/adr/
│   ├── 001-workflow-engine.md
│   └── 002-agent-orchestration.md            (不引入 LangChain/LangGraph 的论证)
├── alembic/versions/
│   ├── 20260504_1300_add_model_calls.py        (rev 7f51c2a48e10)
│   ├── 20260504_1330_add_pipeline_runs_steps.py (rev 9a6e4d127b58)
│   ├── 20260504_1700_add_quotas_and_reserved_cost.py (rev c1e8d3b2f0a9)
│   ├── 20260504_2000_add_production_tables.py  (rev a4d72b91e3c5)
│   ├── 20260504_2030_add_dead_letter_tasks.py  (rev e58c4a1d2b73)
│   ├── 20260505_0900_add_tenant_quota_and_provider_buckets.py (rev c2f9b7a04ef1)
│   ├── 20260505_1100_add_platform_credentials.py (rev 8b1f6c2d4a93)
│   ├── 20260505_1200_add_publish_plan_confirm_real.py (rev 9c2d4e5f6a7b)
│   ├── 20260505_1300_add_feature_flags.py (rev a1b2c3d4e5f6)  ← Track-10
│   ├── 20260505_1500_add_subscription_refunded_at.py (rev b2c3d4e5f6a7)  ← Track-16
│   ├── 20260505_1600_add_model_calls_tenant_id.py (rev c3d4e5f6a7b8)  ← Track-18
│   └── 20260505_1700_add_team_member_role.py (rev d4e5f6a7b8c9)  ← head ★ Track-24
├── app/
│   ├── main.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py                      (含 production v1 + DLQ + tenant_quota + platform_credential 导出)
│   │   ├── dead_letter.py
│   │   ├── model_call.py
│   │   ├── pipeline.py                      (PipelineRun.cost_reserved_usd / .tenant_id)
│   │   ├── production.py
│   │   ├── quota.py                         (v1 user 级 ModelQuota；保留兼容)
│   │   ├── tenant_quota.py                  (★ 配额 v2：TenantQuota + ProviderConcurrencyBucket)
│   │   └── platform_credential.py           (★ 发布执行器：PlatformCredential)
│   ├── routers/
│   │   ├── pipelines.py                     (含 v2 quota / buckets / start_pipeline 切到 tenant 路径)
│   │   ├── production.py                    (含 ★ /publish-plans/{id}/execute + /platforms/* + OAuth 流程)
│   │   ├── dlq.py
│   │   └── scenes.py
│   └── services/
│       ├── model_gateway/
│       │   ├── types.py                     (CallStatus.RATE_LIMITED + RenderRequest.tenant_id/tenant_plan)
│       │   ├── cost.py
│       │   ├── gateway.py                   (run() 入口 acquire/release provider 槽，缺 tenant 自动 user_id 兜底)
│       │   └── providers/
│       │       ├── llm.py / kling.py / siliconflow_video.py
│       │       ├── siliconflow_tts.py
│       │       ├── siliconflow_asr.py / openai_whisper.py
│       │       └── siliconflow_image.py
│       ├── media/
│       │   ├── ffmpeg.py / subtitles.py / segments.py
│       │   └── __init__.py
│       ├── pipeline/
│       │   ├── types.py                     (PipelineContext 加 tenant_id / tenant_plan)
│       │   ├── runner.py                    (start_run 接 tenant_id；_settle_run_state 走 release_tenant；_load_run_tenant 读 user.plan)
│       │   ├── templates.py
│       │   ├── events.py
│       │   ├── persist.py
│       │   ├── dlq.py                       (push 加 user_id 形参，发布执行器 DLQ 用)
│       │   ├── cost.py
│       │   ├── quota.py                     (★ v2 API：get_or_create_tenant / reserve_tenant / release_tenant / count_active_runs_tenant；v1 保留兼容)
│       │   ├── tenant.py                    (★ resolve_tenant_id + plan_defaults + 1 分钟缓存)
│       │   ├── provider_buckets.py          (★ acquire / release / provider_slot ctx mgr / ensure_bucket plan-bump / BucketFull)
│       │   ├── celery_app.py
│       │   ├── tasks.py
│       │   └── agents/
│       │       ├── research.py / script.py
│       │       ├── art.py                   (v3：锚点参考板 + prompt 锁定 + 防漂 negative + 角色 cards 第一位 = 主角)
│       │       ├── video.py
│       │       ├── voice.py                 (v4：ASR words → _build_subtitles_v4_word_aligned；缺 words 退 v3 行级)
│       │       ├── edit.py                  (v5)
│       │       ├── review.py
│       │       └── __init__.py
│       └── publishing/                      (★ 发布执行器 v1)
│           ├── __init__.py                  (re-export executor + adapters)
│           ├── adapters/
│           │   ├── __init__.py              (导入 dry_run / youtube / bilibili 触发自注册)
│           │   ├── base.py                  (PlatformAdapter / PublishRequest / PublishOutcome / PublishError + 注册表)
│           │   ├── dry_run.py               (始终启用，回 mock external_id)
│           │   ├── youtube.py               (真发，需 GOOGLE_CLIENT_ID + plan.meta.confirm_real_publish 安全闸门)
│           │   └── bilibili.py              (stub，引导手动上传)
│           ├── credentials.py               (list/get/upsert/revoke/update_after_publish 平台凭证)
│           ├── oauth.py                     (build_state JWT / build_youtube_authorize_url / complete_youtube_oauth)
│           └── executor.py                  (execute_publish_plan：load plan + 选 adapter + 调 + 写回 + DLQ)
└── Makefile

fliki-clone/
├── src/hooks/
│   ├── use-pipeline-stream.ts
│   ├── use-run-renders.ts
│   ├── use-run-shot-list.ts
│   └── use-dlq.ts
├── src/lib/
│   ├── pipelines.ts                          (含 v2 PipelineQuota.tenant_id/plan/provider_buckets + getPipelineBuckets)
│   ├── production.ts                         (★ 新增 PublishOutcomeOut / PlatformOut / CredentialOut / OAuthStartOut + executePublishPlan / listPlatforms / listPlatformCredentials / startPlatformOAuth / revokePlatformCredentials)
│   └── dlq.ts
└── src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx
   (★ pipeline 页：4 格 stat 加 tenant 徽标 + Provider 桶 utilization bar；
      ArtArtifact 加 v3 一致性徽标 + 锚点缩略图 + shots 网格 🔒 角标；
      VoiceArtifact 加 v4 word 徽标 + 字幕条 word 时间轴；
      PlanRow 加 Upload 执行按钮 + plan.error 显示 + external_id 显示；
      新增 PlatformCredentialsPanel；DeadLetterPanel 保留)

DEVELOPMENT_PLAN.md                                            (顶层路线图)
SESSION_HANDOFF.md                                             (本文件)
~/.cursor/projects/.../canvases/ai-video-agent-workflow.canvas.tsx
```

---

## 9. 本机配置约束（避免下次会话重新踩坑）

```bash
# .env 关键 key（fliki-clone-api/.env）
SILICONFLOW_API_KEY=sk-...                    # 已配
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
KLING_ACCESS_KEY=AQ...                         # 已配
KLING_SECRET_KEY=Gm...                         # 已配
KLING_MODEL=kling-v1-6
LLM_MODEL=deepseek-ai/DeepSeek-V3
TTS_MODEL=FunAudioLLM/CosyVoice2-0.5B          # 之前 fish-speech 已被 SF 下线
ASR_MODEL=FunAudioLLM/SenseVoiceSmall          # VoiceAgent v2 字幕对齐；SenseVoice 不返 duration，走 ffprobe 兜底
IMAGE_MODEL=Kwai-Kolors/Kolors                 # 之前 FLUX.1-schnell 已被 SF 下线
VIDEO_MODEL=Wan-AI/Wan2.2-T2V-A14B
DATABASE_URL_SYNC=postgresql://zhaoguangyuan@localhost:5432/fliki
CELERY_ENABLED=false                           # 默认走 BackgroundTasks
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

ffmpeg 6.0 在 PATH（`/opt/homebrew/bin/ffmpeg`）。
PostgreSQL 走 `peer auth`，user `zhaoguangyuan` 无密码。
Redis 在跑（`redis-cli ping → PONG`）。

---

## 10. 一句话开局（贴到下个会话）

```
延续 2026-05-04 + 05-05 全天会话；交接见 /Users/zhaoguangyuan/project/empty/SESSION_HANDOFF.md。
仓库：https://github.com/gyzhao666-tech/fliki-clone（monorepo）。
🎉 v1 工程闭环全部收口：22 Track 合并完毕（10 天工作量浓缩在一天），pytest 130 PASS，
5 条 alembic 迁移全落库，125+ 路由（含全部业务 + admin + cost + RBAC）。
当前能力：video_full 端到端 + 全发布闭环 + cost 可观测 + admin 后台 + 配额超限实时
toast + 月账单自动邮件 + workspace RBAC：配额 v2 tenant + provider 桶 + 按 tenant
聚合的 model_calls 成本视图（含 provider 横向 bar + 时序折线 dashboard）/
VoiceAgent v4 word-level / ArtAgent v3+v4+v5（多角色 anchor 按 shot.focus_character
逐镜选 + canary 按 tenant_id hash 染色 v4↔v3-prompt-only）/ VideoAgent v2 i2v
多角色 anchor / EditAgent v5 / 发布执行器 v1（dry-run/youtube/bilibili，YouTube
升级 8 MiB chunked PUT + 进度回写 SSE 不再卡 1080p timeout / Fernet 凭证加密 /
OAuth）+ publish 异步化（celery + SSE phase 流 + last_event_id 断网续传）/
DLQ retry 按 task_name 路由 / feature_flags v1 + 后端 admin 路由 + 前端 admin
Feature Flags 管理面板 + admin Metrics dashboard / Stripe 计费 v2 含 charge.refunded
退款打标 + invoice.paid 月账单 PDF 邮件 / 配额超限 / Provider 桶满 SSE 实时 toast /
ADMIN_EMAILS 落 Settings / RBAC v1（workspace member role + 邮箱白名单 fallback）/
DAG 视图 / pytest 130 case 全过。
请直接做（除非我另说）：
(A) T-20 YouTube + Stripe 真账号 e2e（半天，**非代码工作**：配 .env 真 key
    跑一次完整链路 + 写 E2E_VERIFY_REPORT.md）；
(B) T-12 bilibili 自动发布（等 MCN，2-3 天，商务问题）；
(C) T-19 ArtAgent v6 真 multi-IP（等 SiliconFlow / Replicate 端点，外部依赖）；
(D) 长尾（L-01 字幕翻译 / L-02 卡拉 OK 高亮 / L-06 Celery worker Docker /
    L-07-09 ADR 文档 / L-12 i18n 完整覆盖 等等）。
开始前确认：(1) backend cwd 是 fliki-clone-api；(2) alembic head 是 d4e5f6a7b8c9；
            (3) 启动后端不带 --reload；(4) `cd fliki-clone-api && make test` 应 130 PASS；
            (5) 重启 backend 才会加载第二+三+四+五+六波 15 条 Track 新代码（pid 30876 仍在 11:13 旧版）；
            (6) 多 Agent 协作见 AGENTS_BACKLOG.md（仓库根）。
```

## 11. 怎么试 v4 多比例（最快）

在 pipeline 页面把 Brief 里加一行：

```jsonc
{
  "目标平台": ["bilibili"],
  "受众": "...",
  "export_aspects": ["9:16", "16:9", "4:5"],   // ← 触发多比例
  "aspect_fit": "cover"                          // 可选；默认 cover；letterbox 改 "contain"
}
```

启动 `video_full` 模板，跑到 edit 节点后：
- 视频上方出现「导出比例：9:16 16:9 4:5」按钮组，默认选中主比例（来自 art.style_board.aspect_ratio）
- 切换比例 `<video>` 重新加载
- 旁白比拼接视频长 → 顶部出现「视频已循环 ↻」徽标
- ffmpeg 对每个 aspect 跑一次重编码：6 镜 30s 视频 × 3 比例约 30-60s 总耗时
