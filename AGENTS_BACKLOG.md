# 多 Agent 并行 Backlog（2026-05-05 起；第一波 7 + 第二波 4 + 第三波 5 + 第四波 1 Track 全部已合并）

> 这份是**给每个 Cursor Agent Window 看的**：进入仓库第一件事 read 这份，找你的 Track，按规则执行。
> 协调者：人类（用户）；分支合并、SESSION_HANDOFF.md 更新由人类（或最后一个 agent）统一负责。

## 0. 仓库 / 进程现状（2026-05-05 15:00 更新）

- **GitHub**：https://github.com/gyzhao666-tech/fliki-clone（monorepo：`fliki-clone-api/` + `fliki-clone/`）
- **本地仓库根**：`/Users/zhaoguangyuan/project/empty/`
- **基线**：`main` @ `a3c7576 Merge track-18-model-calls-tenant`（第四波最后一条）
- **alembic head**：**`c3d4e5f6a7b8`**（含 `model_calls.tenant_id` 列 + 索引 + backfill；已落 DB；不要重复跑）
- **后端进程**：pid `30876`，监听 `127.0.0.1:8000`（无 proxy 污染）；
  **第二+三+四波合并后这个 pid 还没重启 → 必须 kill + 重启才会加载新代码**：
  ```bash
  kill 30876
  cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
  **不要带 `--reload`**（会启 Python 3.12 子进程，import error）
- **前端进程**：pid `8947`，3000 端口；hot-reload 自动生效不用重启
- **测试基线**：`cd fliki-clone-api && make test` 应得 **89 passed**；改完代码前后都跑一遍
- **背景知识必读**：`SESSION_HANDOFF.md`（项目当前能力 / 已知坑 / 配置约束）

## 0.1 第一波 7 Track 合并状态（2026-05-05 12:35 完成）

| Track | 状态 | 合并 commit |
|---|---|---|
| 01 凭证 Fernet 加密 | ✅ | `d34dd45` |
| 02 YouTube confirm_real_publish 列 | ✅（alembic 9c2d4e5f6a7b） | `8a0a94f` |
| 04 ArtAgent v4 IP-Adapter 接入点 | ✅ | `f701f8e` |
| 05 VideoAgent v2 anchor 主参考帧 | ✅ | `32f1b42` |
| 06 faster-whisper 本地 fallback | ✅ | `9079be9` |
| 07 Pipeline DAG 视图 | ✅ | `e023449` |
| 08 pytest 工程化 31/31 | ✅ | `9378faf` |

## 0.2 第二波 4 Track 合并状态（2026-05-05 13:55 完成）

合并顺序：T11 → T03 → T09 → T10（最后合 T10 解 `art.py` canary × 多角色叠加冲突）。

| Track | 状态 | 合并 commit |
|---|---|---|
| 03 publish 任务异步化（celery + SSE） | ✅ | `af7d888` |
| 09 多角色锁定 v5 | ✅ | `09eeb53` |
| 10 灰度发布 / canary（alembic `a1b2c3d4e5f6`） | ✅ | `f8f8933` |
| 11 Stripe 计费对接 | ✅ | `a355509` |

合并冲突一处（已解决）：`fliki-clone-api/app/services/pipeline/agents/art.py`
T09 v5 多角色 `anchors_url_by_role` 字典 与 T10 canary 闸门叠加。
解法：保留 T09 字典构造；canary 命中 → 字典原样喂；不命中 → 字典清空 → 主角镜降到 prompt-only；
outputs 同时保留 `character_anchors`（v5）+ `canary_variant`/`canary_flag_value`（T10）。
新增 `tests/test_canary_multichar_combo.py` 4 case PASS（叠加点回归保护）。

## 0.3 第三波 5 Track 合并状态（2026-05-05 14:30 完成）

合并顺序：T-15 → T-14 → T-13 → T-17 → T-16（最后合 T-16 因独占 alembic 槽 `b2c3d4e5f6a7`）。

| Track | 状态 | 合并 commit |
|---|---|---|
| 15 DLQ retry 按 task_name 路由 | ✅ | `cbf49bf` |
| 14 Admin Feature Flags UI | ✅（NOTES 由协调者代写）| `12beda8` |
| 13 YouTube chunked PUT + 进度 SSE | ✅ | `2be6bb5` |
| 17 SSE 断网重连 last_event_id | ✅ | `c23162d` |
| 16 Stripe webhook charge.refunded（alembic `b2c3d4e5f6a7`）| ✅ | `2b7ca16` |

合并冲突一处（已解决）：`fliki-clone/src/hooks/use-publish-plan-stream.ts` 顶部 docstring 段。
合 T-13 后再合 T-17 时，T-13 加的 `upload_progress` 协议块与 T-17 想换的 snapshot
协议描述（加 `id:` 行）落在同一段。解法：双方协议块都保留，T-17 的 `id:` 行作为
协议第一条，T-13 的 `upload_progress` 描述独立成段，全部 entry 不丢。

特殊点：Track-14 agent 完成代码 + tests（48 PASS）但忘 `git commit` + 写 NOTES；
协调者用 `git add -A && git commit` 收口，并代写 TRACK_14_NOTES.md（已删除）。
下次派发提示词建议加一句「最后必须 `git status` 确认 working tree clean 才算交付」。

## 0.4 第四波 1 Track 合并状态（2026-05-05 15:00 完成）

| Track | 状态 | 合并 commit |
|---|---|---|
| 18 model_calls 加 tenant_id + 按 tenant 聚合 cost 视图（alembic `c3d4e5f6a7b8`）| ✅ | `a3c7576` |

无合并冲突。alembic 双向迁移测过（upgrade → downgrade -1 → upgrade，列消失再回来不丢数据）。
全量 pytest 89 PASS（79 baseline + 10 新增 4 unit + 6 integration）。

## 1. 通用规则（所有 agent 必须遵守）

1. **每个 Track 一条 feature branch**（已预创建）；进入工作前：
   ```bash
   git checkout track-XX-<your-track>
   ```
2. **不要切换分支**；不要 rebase / merge main；改完留 commit 在 feature branch 上，由人类合并。
3. **alembic 互斥锁**：第五波（待派）暂未占用迁移槽；新 Track 加列时各自约定 rev id（顶 `c3d4e5f6a7b8`），多个 Track 同时加 schema 需要协调者串行合并。
4. **`.env` 互斥锁**：先看 `app/config.py` 是否已有所需字段；新增 settings 字段单独留一个 Track 处理，不要在普通业务 Track 里夹带。
5. **`pipeline/page.tsx` 大文件分段**：每个 Track 卡片必须明确指定动哪个子组件 / hook，不要越界。
6. **commit 完整性 ★ T-14 教训**：完成代码后**必须** `git status` 确认 working tree clean 才算交付（第三波 T-14 写完代码忘 commit + NOTES，让协调者收口）。
7. **commit message 风格**：参考 baseline；中英混合 OK；要写**为什么**（why）而非只列 what。
8. **完成后写一份 `TRACK_<ID>_NOTES.md` 在仓库根**：包含：
   - 改了哪些文件 + 为什么
   - 烟测命令 + 结果
   - 已知边界 / 跳过的子任务
   - 后续 follow-up
9. **不要更新 `SESSION_HANDOFF.md`**（最后由人类统一）。
10. **不要 push 到 remote**（用户没说要 push；本地分支即可）。
11. **不要 `git config --global`**；commit 用 `-c user.name=... -c user.email=...` 即可。
12. **沙盒里 backend 启动会被注入 HTTP_PROXY**（向 SiliconFlow 真发会失败 403）；如果你的烟测要真发外部 API，
    用 `required_permissions: ["all"]` 跑；**算法测 / 单元测可以 mock gateway**避免网络。
13. **写完跑一遍 ReadLints / 看 import 路径**；**不要留 ad-hoc smoke 脚本**（用 pytest 或者跑完即删）。


## 2. 第二波（已全部 merge，留作历史档案）

> **以下 4 条均已合并到 main**（见 0.2 表）。新派发请直接看第 3 节长尾或 SESSION_HANDOFF.md 第 7 节推荐顺序。

### Track-03 · publish 任务异步化 ★★ (半天)

- **分支**：`track-03-publish-async-celery`（已 fast-forward 到最新 main，含 Track-02 confirm_real_publish 列）
- **目标**：当前 `/publish-plans/{id}/execute` 同步等 30-60s；改成入 Celery 即返 202 + SSE 推 `publish_plan_state`
- **修改文件**：
  - `fliki-clone-api/app/services/pipeline/tasks.py`（新增 `execute_publish_plan_task` 绑 DLQAwareTask base）
  - `fliki-clone-api/app/services/pipeline/celery_app.py`（路由 default 队列）
  - `fliki-clone-api/app/routers/production.py`（execute 端点：默认派发 + 202；保留 `?sync=true` 兜底；新加 `GET /publish-plans/{id}/events` SSE）
  - `fliki-clone-api/app/services/pipeline/events.py`（加 `publish_plan_state` 事件类型 + 通道 `publish:plan:{id}`）
  - `fliki-clone/src/hooks/use-publish-plan-stream.ts`（新 hook：EventSource + polling fallback）
  - `fliki-clone/src/app/.../pipeline/page.tsx::PlanRow`（点 Upload 后 hook 订阅；loading 转圈直到 published / failed）
- **互斥锁（独占）**：`tasks.py`、`celery_app.py`、`production.py` execute/SSE 段、`events.py`、`pipeline/page.tsx::PlanRow`
- **依赖**：✅ Track-02 已 merge
- **烟测**：起 redis + `make pipeline-worker`；调 execute 返 202 + plan_id；SSE 拉到 `publish_plan_state`
- **不做**：alembic schema 改

### Track-09 · 多角色锁定 ★ (1 天)

- **分支**：`track-09-multi-character`（已 fast-forward 到最新 main）
- **目标**：v3 / v4 只锁主角；`focus_character != protagonist` 镜被跳过。v5 给每个 character_card 各出一份 anchor，按 `shot.focus_character` 选对应 anchor + 注入对应前缀
- **修改文件**：
  - `fliki-clone-api/app/services/pipeline/agents/art.py`：
    - `_select_protagonist` → 扩 `_select_relevant_characters(brief, character_cards)` 返 list（主角必在；其他 cards 在前 3 个内的也 anchor）
    - `_generate_character_anchor` → 复数版 `_generate_character_anchors(...) -> dict[name, anchor]`
    - `_inject_consistency_into_shots` → 接受 `anchors_by_role: dict`，按 `shot.focus_character` 选；缺时用 protagonist
    - `outputs.character_anchor` → 兼容期保留为「主角 anchor」；新加 `outputs.character_anchors: dict[name, anchor]`
  - `fliki-clone-api/app/services/pipeline/agents/video.py::_select_ref_image`：扩 `anchors_by_role`，按 `focus_character` 选锚点 URL
  - `fliki-clone/src/app/.../pipeline/page.tsx::ArtArtifact`：锚点缩略图 panel 改成支持多角色（横向小卡片列表，每张带角色名）
- **互斥锁（独占）**：`agents/art.py`、`agents/video.py`、`pipeline/page.tsx::ArtArtifact + VideoArtifact`
- **依赖**：✅ Track-04 / Track-05 已 merge
- **烟测**：mock LLM 返 2 角色 cards；art outputs.character_anchors 含 2 个；不同 focus_character 的镜注入不同前缀；video step ref_image_source 按角色选
- **不做**：改 alembic / 引入新表

### Track-10 · 灰度发布 / canary 路由 ★ (1.5 天)

- **分支**：`track-10-canary-flags`（已 fast-forward 到最新 main）
- **目标**：按 `tenant_id` hash 染色，让一部分 tenant 走 ArtAgent v4（IP-Adapter），一部分走 v3（prompt-only）；类似机制可复用到未来任意 agent 版本切换
- **修改文件**：
  - **新 alembic migration**（**独占迁移槽**）：`feature_flags` 表（`tenant_id` / `flag_name` / `value_json` / `created_at`，唯一约束 (tenant_id, flag_name)）
  - `fliki-clone-api/app/models/feature_flag.py`（新 ORM）+ `__init__` 注册
  - `fliki-clone-api/app/services/pipeline/feature_flags.py`（新模块）：`get_flag(tenant_id, name, default) -> Any` / `set_flag(tenant_id, name, value)` / `is_enabled(tenant_id, name, *, default_pct=0)` 按 hash 染色
  - `fliki-clone-api/app/services/pipeline/types.py::PipelineContext`：加 `feature_flags: dict[str, Any]` 字段
  - `fliki-clone-api/app/services/pipeline/runner.py::execute_step`：build ctx 时一并加载 flags
  - `fliki-clone-api/app/services/pipeline/agents/art.py`：在 `run` 入口读 `ctx.feature_flags.get("art_ipadapter_pct", 100)`，按 hash 决定走 v4 还是降级到 v3 prompt-only
  - 新路由 `app/routers/admin_flags.py`：`GET/PUT/DELETE /api/admin/flags`（按 tenant + flag_name CRUD；admin 鉴权简化为 user.email in ALLOWED_ADMINS）
- **互斥锁（独占）**：alembic 槽、`feature_flag.py`、`feature_flags.py`、`runner.py::execute_step`（小段 ctx build）、`agents/art.py` 入口几行、`routers/admin_flags.py`
- **依赖**：✅ Track-01 已 merge
- **不做**：前端 admin 后台（留给后续）；只暴露 API 端点
- **烟测**：建 1 个 tenant 设 `art_ipadapter_pct=50` → 跑两次 video_full → 50% 命中 v4；改 100 → 全部 v4；改 0 → 全部 v3

### Track-11 · Stripe 计费对接（plan 升级）★★ (2 天)

- **分支**：`track-11-stripe-billing`（已 fast-forward 到最新 main）
- **目标**：用户在前端 `/app/billing` 升级 free → standard → premium 时，Stripe webhook 落到 `tenant_quotas.plan` + 自动 bump `monthly_limit_usd` / `concurrent_max` / 各 provider bucket max
- **修改文件**：
  - 新路由 `fliki-clone-api/app/routers/billing.py`：
    - `POST /billing/checkout-session`：返 Stripe Checkout URL（按 user.id + 目标 plan）
    - `POST /billing/portal-session`：返 Stripe Customer Portal URL
    - `POST /billing/webhook`：监听 `checkout.session.completed` / `customer.subscription.{created,updated,deleted}` → 同步到 `subscriptions` + `tenant_quotas`
  - `fliki-clone-api/app/services/billing/`（新模块）：`stripe_client.py` + `webhook_handlers.py` + `tenant_sync.py`
  - `fliki-clone-api/app/services/pipeline/quota.py`：新加 `update_tenant_plan(tenant_id, new_plan)` 自动调 limit/concurrent + ensure_bucket bump
  - `fliki-clone/src/app/[locale]/(app)/app/billing/page.tsx`（新页面）：plan 卡片 + 当前订阅 + 升级按钮 + 跳 Stripe Portal 按钮
  - `fliki-clone-api/.env.example` 加 `STRIPE_PRICE_FREE` / `STRIPE_PRICE_STANDARD` / `STRIPE_PRICE_PREMIUM`（实际值 user 自己 .env）
- **互斥锁（独占）**：`billing.py`、`services/billing/`、`quota.py::update_tenant_plan`（新函数）、新前端 `app/billing/page.tsx`
- **依赖**：✅ Track-01 已 merge（`subscriptions` 表已存在）；现有 `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` 配置项已有
- **烟测**：用 Stripe CLI 触发 webhook（`stripe trigger checkout.session.completed`）→ DB 看 subscriptions + tenant_quotas.plan 同步；走 checkout 页面真买（test mode 卡 `4242...`）→ 即时升级 → quota.concurrent_max 跟随
- **不做**：处理失败支付 / 退款 / proration（v1 范围之外）

### Track-12 · bilibili 自动发布（依赖商务入驻）★ (2-3 天)
- 等 MCN OpenAPI；技术骨架已在 `adapters/bilibili.py` 留好

## 2.5 第三波（已全部 merge，留作历史档案）

> **以下 5 条均已合并到 main**（见 0.3 表）。新派发请直接看 2.6 节第四波。

### Track-13 · YouTube chunked PUT + 真账号 e2e ★★ (半天)

- **分支**：`track-13-youtube-chunked-upload`
- **目标**：当前 `adapters/youtube.py` 用 resumable upload 一把发，1080p / 60s+ 视频易触 60s HTTP timeout。改成 8 MiB 分片 chunked PUT + 进度回写 `plan.meta_json.upload_progress`，每片完通过 SSE 推 `upload_progress` 事件让前端进度条流畅。
- **修改文件**：
  - `fliki-clone-api/app/services/publishing/adapters/youtube.py`：拆 `_initiate_upload()` 拿 upload_url；新加 `_chunked_put(upload_url, video_bytes_iter, chunk_size=8*1024*1024, on_progress=cb)` → 每片带 `Content-Range: bytes X-Y/total`，HTTP 308 滚到下一片，最后片返 200 + `{id: video_id}`；5xx/408/429 指数退避重试每片最多 3 次
  - `fliki-clone-api/app/services/publishing/executor.py`：execute_plan 给 youtube adapter 传 `progress_cb = lambda info: _write_progress(plan_id, info)`；cb 内开新 session UPDATE `publish_plans.meta_json` JSONB merge `{"upload_progress": info}` + 调 `publish_plan_event(plan_id, "upload_progress", info)` 推 SSE
  - `fliki-clone/src/hooks/use-publish-plan-stream.ts::handleEvent`：switch case 加 `upload_progress` → 调 `onEvent({type: "upload_progress", percent, bytes_uploaded, total})`
  - `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx::PlanRow`：执行中 + 收到 upload_progress 后渲染 `<Progress value={percent}/>` 带 `{bytes_uploaded}/{total}` 文案
- **互斥锁（独占）**：`adapters/youtube.py`、`executor.py` 进度 cb 段、`use-publish-plan-stream.ts::handleEvent` switch case（与 Track-17 互不干涉，T-17 改的是底层 EventSource 框架）、`pipeline/page.tsx::PlanRow` 进度条段
- **依赖**：✅ Track-03 已合（事件流通道复用）；✅ Track-01 已合（Fernet 凭证）
- **烟测**：
  - 单元：mock httpx 让首请求返 `Location: ...?upload_id=`，每片返 308 + Range，最后片返 200 → 断 progress_cb 被调 N 次（N = 总片数）+ 重试逻辑（5xx → 指数退避）
  - 真账号 e2e（用户配真 GOOGLE_CLIENT_ID + OAuth）：60MB 测试 mp4 → SSE 流应看到 0%→13%→26%→...→100% 进度推送 + `external_id` 真 youtube id
- **不做**：alembic schema 改；bilibili 适配（Track-12 商务问题）

### Track-14 · 前端 Admin · Feature Flags 管理面板 ★ (1 天)

- **分支**：`track-14-admin-flags-ui`
- **目标**：把 Track-10 的 `/api/admin/feature-flags` HTTP API 包装成可视化面板。Admin（`ADMIN_EMAILS` 邮箱白名单）能列 tenant 的 flag、改 pct 滑块、Apply、查看变更历史。
- **修改文件**：
  - **新页面** `fliki-clone/src/app/[locale]/(app)/app/admin/feature-flags/page.tsx`：
    - 顶部 tenant 选择器（拉 `/api/admin/feature-flags/tenants` 列表）
    - 表格：flag_name / value（pct 滑块 0-100 / enabled toggle / variant 下拉）/ updated_at / Apply / Delete
    - 「新增 flag」dialog：从 known list 选 flag_name + 形态
  - **新** `fliki-clone/src/lib/admin-flags.ts`：TS 类型（`AdminFlagOut`）+ fetch helper（`listTenants` / `listTenantFlags(tid)` / `setTenantFlag(tid, name, value)` / `deleteTenantFlag(tid, name)`）
  - `fliki-clone/src/components/app-shell.tsx`（或 settings 侧栏）：admin 邮箱命中时多一个「Admin · Feature Flags」入口（tsx 文件名按现有结构调整）
  - `fliki-clone-api/app/routers/admin_flags.py`：加 `GET /api/admin/feature-flags/tenants` → `SELECT DISTINCT tenant_id FROM feature_flags ORDER BY tenant_id`；admin 鉴权同既有
- **互斥锁（独占）**：前端 admin 目录全部新文件、`src/lib/admin-flags.ts`、`admin_flags.py` 加 list-tenants 端点（小段独占）
- **依赖**：✅ Track-10 已合
- **烟测**：admin 邮箱登录 → 进 `/app/admin/feature-flags` → 选 tenant → 改 pct=50 → Apply → 后端 PUT 落库 → 该 tenant 下次跑 video_full 看 outputs.canary_variant 50/50 分布
- **不做**：完整 RBAC（L-05 长尾）；后端 audit log 落库（先前端 stub）

### Track-15 · DLQ retry 识别 publish task ★ (1-2 小时)

- **分支**：`track-15-dlq-retry-publish`
- **目标**：当前 `routers/dlq.py::_retry_dispatch` 把所有死信都 dispatch 到 `tick_task`；publish.execute_plan 死信被重试时 worker 收到的是 tick task 不会真重发布。识别 task_name 路由到正确的 task。
- **修改文件**：
  - `fliki-clone-api/app/routers/dlq.py::_retry_dispatch(dead, background_tasks)`：加 task_name 分支
    ```python
    if dead.task_name == "publish.execute_plan":
        from app.services.pipeline.tasks import (
            execute_publish_plan_task, _publish_execute_with_events,
        )
        plan_id = (dead.args or [None])[0]
        user_id = (dead.kwargs or {}).get("user_id")
        if settings.celery_enabled:
            execute_publish_plan_task.apply_async(args=[plan_id], kwargs={"user_id": user_id}, queue="default")
        else:
            background_tasks.add_task(_publish_execute_with_events, plan_id, user_id)
    else:
        # 既有 tick_task 路径
        ...
    ```
  - `fliki-clone-api/tests/test_dlq_retry_publish.py`（新文件）：构造一条 `task_name="publish.execute_plan"` 的死信 + monkeypatch `execute_publish_plan_task.apply_async` → 调 `_retry_dispatch` 断 mock 被调一次（celery 路径）+ BackgroundTasks 路径同样断 add_task 收到正确函数引用
- **互斥锁（独占）**：`routers/dlq.py::_retry_dispatch` 函数体（小段；不影响其它 dlq 路由）
- **依赖**：✅ Track-03 已合
- **烟测**：单元测试 PASS；可选人工：用前端 DLQ panel 把一条 publish 死信 retry，看 `dead_letter_tasks.status='retried'` + redis `default` 队列收到 `publish.execute_plan` payload
- **不做**：DLQ 死信批量 retry / 自动 retry 策略 / time_limit 硬超时

### Track-16 · Stripe webhook 单元测试 + 退款事件 ★★ (半天)

- **分支**：`track-16-stripe-webhook-tests`
- **目标**：(1) pytest 套件目前没覆盖 Track-11 webhook handlers；用模拟 stripe Event 跑 `handle_webhook_event` 断言 DB 变化，5 种事件全覆盖。(2) 补 `charge.refunded` 事件：写 `subscriptions.refunded_at` 打标，**不动** `tenant_quotas`（保留当月配额到自然月末，用户体验优先；后续 ops 工具人手回滚）。
- **修改文件**：
  - **新 alembic** `fliki-clone-api/alembic/versions/20260505_1500_add_subscription_refunded_at.py`（rev `b2c3d4e5f6a7`，顶 `a1b2c3d4e5f6`）：加 `subscriptions.refunded_at: TIMESTAMP NULL`
  - `fliki-clone-api/app/models/subscription.py`：加 `refunded_at: Optional[datetime]`
  - `fliki-clone-api/app/services/billing/webhook_handlers.py`：加 `_handle_charge_refunded(event)` → UPDATE `subscriptions.refunded_at = now()` WHERE `stripe_charge_id = event.data.object.id`；不调 `sync_user_plan`；事件矩阵字典加 `"charge.refunded": _handle_charge_refunded`
  - `fliki-clone-api/tests/test_billing_webhook.py`（新文件）：本文件内定义 `make_event(type, **fields)` helper（不污染 conftest）；6 个 case 覆盖：
    - checkout.session.completed → `subscriptions` insert + `tenant_quotas.plan` 同步
    - customer.subscription.updated → plan 切换
    - customer.subscription.deleted → 切回 free
    - invoice.payment_failed → 写日志（v1 不改 DB）
    - charge.refunded → `subscriptions.refunded_at` 写入；`tenant_quotas.plan` 不变
    - 未知事件 → handled=False
- **互斥锁（独占）**：alembic 槽 rev `b2c3d4e5f6a7`、`models/subscription.py` 加列、`services/billing/webhook_handlers.py` 加新 handler 函数、新 `tests/test_billing_webhook.py`
- **依赖**：✅ Track-11 已合
- **烟测**：`pytest tests/test_billing_webhook.py -v` 6/6 PASS；`alembic upgrade head` + `downgrade -1` + `upgrade head` 来回测一次
- **不做**：邮件通知（L-04 长尾）；自动配额回滚（v1 故意不做）

### Track-17 · SSE 断网重连 last_event_id ★ (半天)

- **分支**：`track-17-sse-resume`
- **目标**：当前 SSE 在网络抖动断流后客户端只能从 `snapshot` 重头拉，丢一批 step_state；改成 redis Stream（XADD/XREAD）+ 服务端响应每条事件带 `id:` 字段 + 服务端读 `Last-Event-ID` 头从断点恢复，浏览器 EventSource 原生支持自动断网重连续传。
- **修改文件**：
  - `fliki-clone-api/app/services/pipeline/events.py`：
    - `_publish_to_channel(channel, payload)`：双写 redis pub/sub（保留兼容） + redis Stream `XADD {channel}:stream * data <json>`（自动 id）；`MAXLEN ~ 1000` trim
    - `_subscribe_channel(channel, *, last_event_id=None, stop_event)`：从 last_event_id（或 `$`）起 `XREAD BLOCK 1000ms`；事件 envelope 多带 `id` 字段；保留 idle yield None 让上层心跳
  - `fliki-clone-api/app/routers/pipelines.py::stream_run_events`：读 `request.headers.get("Last-Event-ID")` 传给 subscribe；SSE 每条事件 emit `id: {event_id}\n` 在 `event:` 之前
  - `fliki-clone-api/app/routers/production.py::stream_publish_plan_events`：同样改
  - `fliki-clone/src/hooks/use-pipeline-stream.ts::buildEventSource`：原生 EventSource 自动带 Last-Event-ID 头不用前端改；只需保证 hook **不在** onerror 时强制重置（让浏览器自然重连即可）
  - `fliki-clone/src/hooks/use-publish-plan-stream.ts::buildEventSource`：同
- **互斥锁（独占）**：`services/pipeline/events.py` 内核（与 Track-15 / Track-16 不冲突）、两个 router 的 SSE generator 段、两个前端 hook 的 `buildEventSource()` 段（**与 Track-13 错峰**：T-13 改 `handleEvent` switch case 加 upload_progress；T-17 改 `buildEventSource` connection 框架；同文件不同函数）
- **依赖**：✅ Track-03 已合
- **烟测**：起 backend → curl `-N -H "Accept: text/event-stream"` 拉 SSE 几条事件 → kill curl 模拟断网 → 用 `-H "Last-Event-ID: <prev_id>"` 重连 → 应只收 prev 之后的事件；附 unit：mock redis `XREAD` 返事件断 envelope.id 单调递增
- **不做**：多客户端 fan-out 优化；redis Stream 跨进程 consumer group

---

## 2.6 第四波（已全部 merge，留作历史档案）

> **以下 1 条已合并到 main**（见 0.4 表）。新派发请直接看 2.7 节第五波候选。

### Track-19 · ArtAgent v6 多角色 IP-Adapter 真接入 ★ (1-1.5 天) ⏸ 等外部依赖

- **分支**：`track-19-multi-ip-adapter`（不创建本地分支，标 ⏸）
- **依赖**：等 SiliconFlow Kolors-IP / Replicate Flux Redux 出 multi-IP 端点；当前 Track-09 已留 `anchors_by_role` 接入点

## 2.7 第五波候选（待派；可同时派发）

> 当前 v1 核心闭环已就绪，剩余都是「优化 / 长尾」。建议派发节奏：3-5 个 Cursor Agent Window 同时跑，每个半天到 1.5 天。

| 优先级 | Track ID | 内容 | 工作量 | 互斥锁 |
|---|---|---|---|---|
| ★★ | T-20 | YouTube + Stripe 真账号 e2e（用户配真 key 跑一次完整链路；写 e2e 报告 + 截图） | 半天 | 不动代码（仅文档 + .env 配置 + 跑) |
| ★ | T-21 | L-03 metric dashboard 升级（用 T-18 的 model_calls.tenant_id 做按天 / provider 时序图；新前端 `/app/admin/metrics` 页面 + 后端 `/api/cost/timeseries` 端点） | 1.5 天 | 后端 `routers/cost.py` 加 `/timeseries` 段；前端独占新页面 |
| ★ | T-22 | L-04 月账单 PDF + 邮件（拿 stripe `invoice.paid` 渲染 PDF + 调 fastapi-mail 发送） | 1 天 | 后端独占 `services/billing/invoice_pdf.py` + `services/email/` 新模块 |
| ★ | T-23 | L-13 `ADMIN_EMAILS` 迁回 `Settings`（Track-10/14/18 都通过 `os.environ` 直读，本 Track 一次性收口） | 0.5 天 | 改 `app/config.py` 加字段；前端不动 |
| ★ | T-24 | L-05 真 RBAC（workspace member editor/viewer/admin role；替换 Track-10/14 邮箱白名单） | 1.5 天 | 新 alembic 加 `team_members.role` 列 + 改 `_require_admin` 逻辑 |
| ★ | T-25 | L-10 配额超限 SSE 实时推送（用 T-17 redis Stream 框架推 `quota_exceeded` 事件给前端 toast） | 半天 | 改 `services/pipeline/quota.py::reserve` 抛事件；前端 hook 订阅 |

## 3. 长尾（任意时机）

| ID | 任务 | 工作量 |
|---|---|---|
| L-01 | 字幕翻译 + 多语言版本 | 1 天 |
| L-02 | 卡拉 OK 高亮联动 audio.timeupdate | 半天 |
| L-03 | metric dashboard（cost / view_count 时序） | 1.5 天 |
| L-04 | 月账单 PDF 导出 + 邮件（依赖 Track-11 webhook `invoice.paid`） | 1 天 |
| L-05 | RBAC：workspace member editor/viewer 权限（替换 Track-10 admin 邮箱白名单） | 1.5 天 |
| L-06 | Celery worker Docker + supervisor | 半天 |
| L-07 | ADR-003 凭证加密策略 | 0.5 天 |
| L-08 | ADR-004 多平台发布 SLA | 0.5 天 |
| L-09 | ADR-005 角色一致性 v3→v4→v5→LoRA 演进 | 0.5 天 |
| L-10 | 配额超限 SSE 实时推送 | 半天 |
| ~~L-11~~ → T-18 | ~~model_calls 加 tenant_id~~ → 移到第三波 | 半天 |
| L-12 | 前端 i18n 完整覆盖 | 1.5 天 |
| L-13 | Track-10 `ADMIN_EMAILS` 从 env 直读迁回 `Settings`（Track-01 互斥锁已解除） | 0.5 天 |

## 4. 给单个 Cursor Agent Window 的标准开工提示词

> 复制下面这段，把 `<TRACK_ID>` 换成具体编号，开新 Agent Window 时粘贴进去。

```
你是 Track-<TRACK_ID> 的负责 agent。请按以下顺序行动：

1. 先 `git checkout track-<TRACK_ID>-...` 切到你的 feature branch
2. read /Users/zhaoguangyuan/project/empty/AGENTS_BACKLOG.md 找到你的 Track 卡片
3. read /Users/zhaoguangyuan/project/empty/SESSION_HANDOFF.md 了解项目当前能力 + 已知坑
4. 严格遵守 AGENTS_BACKLOG.md 第 1 节「通用规则」（互斥锁、不改 main、不更 SESSION_HANDOFF、不要 push）
5. 完成范围内代码 + 烟测；commit 到本 feature branch
6. 在仓库根写一份 TRACK_<TRACK_ID>_NOTES.md：改了什么、烟测结果、follow-up
7. 报告完成；不要切回 main，不要合并

如果发现你的 Track 与其他 Track 共享同一文件冲突，立即停止并向人类报告，不要私自越界。

工作目录：/Users/zhaoguangyuan/project/empty
```

## 5. 协调者（人类）的合并 checklist

每个 Track agent 完成后，人类按这个顺序合并：

1. `git checkout main`
2. 看 `TRACK_XX_NOTES.md` 验收
3. 在 backend 跑一遍该 Track 的烟测（命令在 NOTES 里）
4. `git merge --no-ff track-XX-...`（保留 merge 提交）
5. 删 feature branch：`git branch -d track-XX-...`
6. 删 `TRACK_XX_NOTES.md`（合并到 SESSION_HANDOFF.md）
7. 重启 backend；前端 hot-reload
8. 更新 `SESSION_HANDOFF.md` 反映新能力
9. 新 baseline commit

**alembic 串行**：Track-02 完成合并后，Track-03 / 后续 agent 启动前必须 `git merge main` 拿到新 head；如果 alembic head 改了，所有未启动的 agent 也要在 prompt 里把 head 号刷新。
