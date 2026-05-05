# 多 Agent 并行 Backlog（2026-05-05 起；第一波 7 + 第二波 4 + 第三波 5 + 第四波 1 + 第五波 4 + 第六波 1 + 第七波 5 = 27 Track 全部已合并）

> 这份是**给每个 Cursor Agent Window 看的**：进入仓库第一件事 read 这份，找你的 Track，按规则执行。
> 协调者：人类（用户）；分支合并、SESSION_HANDOFF.md 更新由人类（或最后一个 agent）统一负责。

## 0. 仓库 / 进程现状（2026-05-05 17:35 更新 · 第七波合并完成 · 27 Track 全合）

- **GitHub**：https://github.com/gyzhao666-tech/fliki-clone（monorepo：`fliki-clone-api/` + `fliki-clone/`）
- **本地仓库根**：`/Users/zhaoguangyuan/project/empty/`
- **基线**：`main` @ `be6616b Merge track-27-rbac-editor-viewer`（第七波最后一条；下方还会有 coordinator 收口 commit）
- **alembic head**：**`d4e5f6a7b8c9`**（含 `team_members.role`；本批 0 新迁移；已落 DB；不要重复跑）
- **后端进程**：pid `30876`，监听 `127.0.0.1:8000`（无 proxy 污染）；
  **5 + 22 = 27 Track 全合后这个 pid 仍是 12:40 旧版 → 必须 kill + 重启才能加载第二+三+四+五+六+七波 20 条 Track 新代码**：
  ```bash
  kill 30876
  cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
  **不要带 `--reload`**（会启 Python 3.12 子进程，import error）
- **前端进程**：pid `5202`（next dev），3000 端口；hot-reload 自动生效不用重启
- **测试基线**：`cd fliki-clone-api && make test` 应得 **146 passed**（130 + T-30 6 + T-27 10）；改完代码前后都跑一遍
- **背景知识必读**：`SESSION_HANDOFF.md`（项目当前能力 / 已知坑 / 配置约束）

> **v1 收口后第一波长尾闭合**：T-26 卡拉 OK / T-27 RBAC editor-viewer / T-28 Celery
> Docker / T-29 ADR 三连 / T-30 workspace 切换 UI 全部合并；剩余仍是 3 个外部 / 商务依赖
> （T-20 真账号 e2e 半天非代码 / T-12 bilibili 等 MCN / T-19 真 multi-IP 等 SiliconFlow）。

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

## 0.5 第五波 4 Track 合并状态（2026-05-05 15:50 完成）

合并顺序：T-25 → T-22 → T-21 → T-23（T-23 留最后吸收 `.env.example` SMTP_*+ADMIN_EMAILS 区域冲突；
`config.py` 由 git auto-merge 自动并入两组字段：T-22 加 SMTP_* 在 stripe_price_* 之后，T-23 加 admin_emails 在末尾）。

| Track | 状态 | 合并 commit |
|---|---|---|
| 25 配额超限 / Provider 桶满 SSE 实时推送 | ✅ | `c543ed1` |
| 22 月账单 PDF + SMTP 邮件（invoice.paid） | ✅ | `cf7eb19` |
| 21 metric dashboard（cost 时序图 + admin metrics 页） | ✅ | `315cdd0` |
| 23 ADMIN_EMAILS 迁回 Settings | ✅ | `8758721` |

合并冲突一处（已解决）：`fliki-clone-api/.env.example` 顶部段。
T-22 在 stripe_price_* 之后加 SMTP_* + INVOICE_EMAIL_ENABLED 一段；T-23 想加 ADMIN_EMAILS 紧随其后。
解法：保留 T-22 SMTP 段完整 + T-23 ADMIN_EMAILS 段紧跟其后，用空行隔开；`config.py` 自动合并通过。

`alembic head` 仍是 `c3d4e5f6a7b8`（本批没人占迁移槽，T-24 留下次）。
全量 pytest 120 PASS（89 baseline + 10 T-25 + 7 T-22 + 8 T-21 + 6 T-23）。

## 0.6 第六波 1 Track 合并状态（2026-05-05 16:30 完成 · v1 工程闭环收口）

| Track | 状态 | 合并 commit |
|---|---|---|
| 24 RBAC v1（workspace member role + 邮箱白名单 fallback；alembic `d4e5f6a7b8c9`）| ✅ | `a1c8c80` |

无合并冲突。alembic 双向迁移测过（upgrade → downgrade -1 → upgrade，列消失再回来不丢数据）。
全量 pytest 130 PASS（120 baseline + 10 新增 RBAC 三路径 / cache TTL / alembic 列存在 / owner backfill / `_require_admin` 集成）。

> **v1 工程闭环全部收口**：22 个 Track 合并完毕，5 条 alembic 迁移全落库（`7f51c2a48e10` →
> `9a6e4d127b58` → `c1e8d3b2f0a9` → `a4d72b91e3c5` → `e58c4a1d2b73` → `c2f9b7a04ef1` →
> `8b1f6c2d4a93` → `9c2d4e5f6a7b` → `a1b2c3d4e5f6` → `b2c3d4e5f6a7` → `c3d4e5f6a7b8` →
> `d4e5f6a7b8c9`），125+ 路由（含 v1 全部业务 + admin + cost + RBAC）。距离真正上线
> 只差 **T-20 真账号 e2e**（半天，**非代码**，由协调者自跑）。

## 0.7 第七波 5 Track 合并状态（2026-05-05 17:35 完成 · v1 收口后第一波长尾闭合）

合并顺序：T-29 → T-28 → T-26 → T-30 → T-27（T-27 与 T-26 在 `pipeline/page.tsx`
顶部 import 段相邻冲突，手解保留双方）。

| Track | 状态 | 合并 commit |
|---|---|---|
| 26 卡拉 OK 字幕高亮（前端 hook + VoiceArtifact 抽组件 + 14 单测）| ✅ | `506ce15` |
| 27 RBAC editor/viewer 写权限分级（rbac.py 加 is_editor/is_viewer/require_role + 14 写端点 + 前端 disable + 10 单测）| ✅ | `be6616b` |
| 28 Celery worker Docker（Dockerfile×2 + docker-compose + .dockerignore×3 + Makefile docker-* + docs/deployment.md）| ✅ | `f609603` |
| 29 ADR 003+004+005（凭证 / SLA / 一致性演进 561 行）| ✅ | `32f107d` |
| 30 workspace 切换 UI + 后端 GET /api/team/workspaces/me + 6 单测 | ✅ | `db17a58` |

`alembic head` 仍是 `d4e5f6a7b8c9`（本批没人占迁移槽）。
全量 pytest **146 PASS**（130 baseline + 6 T-30 + 10 T-27）。

> **协调者前置修复**：本批开工前发现 `make test` 长期显示 75 PASS / 55 FAIL，
> 根因是 Makefile 用 PATH 上的 framework pytest（缺 `pytest-asyncio` 让 async case
> 误判 sync 失败）。改成 `.venv/bin/python -m pytest` 后 **130 PASS** 是真基线，
> 才让本波 5 agent 能信任 baseline 跑测试（详见 commit `292f4ff`）。

> **多 agent 共享 worktree 的副作用**：5 agent 在同一物理仓库切分支 + 写文件 + commit，
> 出现两次「commit 落错分支」需要 cherry-pick 搬回（T-29 / T-26 都遇到了，最终都
> 修正到正确 branch）；T-30 用 `/tmp` 备份 + 选择性 stash 隔离自己的 8 个文件不
> 污染其它 agent。下次派多 Agent 时建议：(1) 用 `git worktree add ../tx-XX <branch>`
> 给每个 agent 物理隔离的 worktree；(2) 或派少量 agent 串行减少切分支次数；
> (3) commit 必走显式 `git add <file>` 不要走 `git add -A`。

## 1. 通用规则（所有 agent 必须遵守）

1. **每个 Track 一条 feature branch**（已预创建）；进入工作前：
   ```bash
   git checkout track-XX-<your-track>
   ```
2. **不要切换分支**；不要 rebase / merge main；改完留 commit 在 feature branch 上，由人类合并。
3. **alembic 互斥锁**：v1 工程闭环已收口；新 Track 加列时各自约定 rev id（顶 `d4e5f6a7b8c9`），多 Track 同时加 schema 需协调者串行合并。
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

> **以下 1 条已合并到 main**（见 0.4 表）。新派发请直接看 2.8 节第六波。

## 2.7 第五波（已全部 merge，留作历史档案）

> **以下 4 条已合并到 main**（见 0.5 表）。新派发请直接看 2.8 节第六波。

### Track-20 · YouTube + Stripe 真账号 e2e（**协调者自跑，不开 Agent**）★★ (半天)

- **不创建 feature branch**（不动代码）
- **目标**：跑通真账号端到端，留一份验收报告 + 截图，确认 v1 核心发布闭环 + 计费闭环真实可用
- **前置准备**：
  - YouTube：申请 Google Cloud OAuth client（type=desktop / web，scope `https://www.googleapis.com/auth/youtube.upload`）→ `.env` 配 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
  - Stripe：登录 dashboard.stripe.com test mode → 复制 `STRIPE_SECRET_KEY=sk_test_...` + 创建 3 个 product + 3 个 price → 拷贝 `STRIPE_PRICE_STANDARD/PREMIUM/FREE` 到 `.env`
  - 启 Stripe CLI 转发 webhook：`stripe listen --forward-to http://127.0.0.1:8000/api/billing/webhook` → 拷贝 webhook signing secret 到 `.env`
- **执行步骤**：
  1. 重启 backend（带新 `.env`）
  2. 跑一次 60 MB+ 测试视频走 video_full → execute publish_plan → 看 SSE 流 0%→100% + `external_id` 真 youtube id
  3. 浏览器访问 `/app/billing` → 点 Upgrade → Stripe Checkout 用 4242 卡 → 跳回看 plan badge active + 看 backend log 收 webhook
  4. 测一次退款：stripe dashboard 找上面那笔 → Refund → 看 webhook log + DB `subscriptions.refunded_at` 写入
- **交付物**：在仓库根写 `E2E_VERIFY_REPORT.md`：截图 + log 摘要 + 通过/失败结论
- **不做**：bilibili 真发（依赖 MCN）；任何代码改动

### Track-21 · L-03 metric dashboard：cost 时序图 + admin metrics 页 ★ (1.5 天)

- **分支**：`track-21-metric-dashboard`
- **目标**：在 T-18 已写入的 `model_calls.tenant_id` 之上做按天 / provider 时序图，让 admin 一眼看出某 tenant 的成本走势
- **修改文件**：
  - 后端 `fliki-clone-api/app/routers/cost.py`：加 `GET /api/cost/timeseries?tenant_id=&provider=&period=daily|weekly&days=30`，返 `[{date, provider, cost_usd, call_count}]`（按 `DATE_TRUNC('day', created_at)` 聚合 + 可选 provider filter）
  - 前端新页面 `fliki-clone/src/app/[locale]/(app)/app/admin/metrics/page.tsx`：tenant 选择器（复用 T-14 的 `listAdminTenants`）+ provider 多选 chips + period toggle + 折线图（推荐用 `recharts` 已在 deps 里）+ 顶部数字 `total_cost / total_calls`
  - 前端 `fliki-clone/src/lib/cost.ts`：加 `getCostTimeseries(args)` + `CostTimeseriesPoint` 类型
  - 前端 `fliki-clone/src/components/app-shell/sidebar.tsx`：admin 命中时多渲一个「Admin · Metrics」入口（与 Feature Flags 并列）
  - 新 `fliki-clone-api/tests/test_track21_timeseries.py` 6+ case：聚合 SQL 正确性 / 缺 provider filter 走全部 / 跨天界限 / 空数据返空数组 / admin 鉴权穿透（复用 `_resolve_query_tenant`）
- **互斥锁（独占）**：
  - 后端 `routers/cost.py` 末尾加 `/timeseries` 段（不改既有 `/summary` `/recent`）
  - 前端 `app/admin/metrics/` 新目录全部独占
  - `lib/cost.ts` 加新 helper（不动既有 `getCostSummary` / `getRecentCostCalls`）
  - `sidebar.tsx::adminLinks` 数组加一项（与 T-14 的 admin 入口并列；T-14 已合，文件可读可改）
- **依赖**：✅ T-18 已合（`model_calls.tenant_id` 列）；✅ T-14 已合（admin 鉴权 + tenant 列表）
- **烟测**：
  - 单元：mock SQL 返若干行 → endpoint 返期望结构
  - 集成：seed 跨 7 天的 model_calls 行 → `?period=daily&days=7` 应返 7 行 / provider；`?provider=siliconflow` 仅返该 provider 的行
- **不做**：图表 zoom/export（v1 静态图够用）；不动 `/summary` `/recent`

### Track-22 · L-04 月账单 PDF + 邮件 ★ (1 天)

- **分支**：`track-22-invoice-pdf-email`
- **目标**：拿 stripe `invoice.paid` 事件 → 渲染 PDF（plan + 期内 cost 拆分 + tenant 名称）→ 调 SMTP 发送给 user.email
- **修改文件**：
  - 后端新模块 `fliki-clone-api/app/services/billing/invoice_pdf.py`：用 `reportlab`（轻量；放到 requirements 里）渲染 A4 PDF，含 logo / period / plan / 按 provider 拆分表格 / 总金额
  - 后端新模块 `fliki-clone-api/app/services/email/__init__.py` + `smtp_client.py`：薄封装 stdlib `smtplib`（不引第三方）；缺 SMTP 配置时抛 `EmailNotConfigured` → router 翻 503
  - 后端 `fliki-clone-api/app/services/billing/webhook_handlers.py`：加 `invoice.paid` dispatch 分支 → `_handle_invoice_paid(invoice, *, event_id)`：找到对应 user → 调 invoice_pdf.render → 调 email.send_invoice → 写 `subscriptions.last_invoice_url`（如果有需要也行可不需要）；缺 SMTP / reportlab 时返 `{handled:True, sent:False, reason:...}` 让 stripe 不重投
  - `.env.example` 加 `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM`（实际值 user 自己 .env）
  - `app/config.py` 加 5 条 settings 字段（SMTP_*）+ `invoice_email_enabled: bool = False`（缺省关闭，避免本地误发）
  - `requirements.txt` 加 `reportlab>=4.0`
  - 新 `fliki-clone-api/tests/test_track22_invoice_email.py` 5+ case：渲染 PDF 字节非空 + 含 plan/provider 字符串 / SMTP 缺配置抛 EmailNotConfigured / `_handle_invoice_paid` mock smtp 正确调用 / 缺 user.email 安全跳过
- **互斥锁（独占）**：
  - 新 `services/billing/invoice_pdf.py`、`services/email/` 模块
  - `services/billing/webhook_handlers.py::_HANDLERS` 字典加一项 + 新 handler 函数（与 T-16 的 5 既有 handler 共存，不改 dispatch 入口）
  - `app/config.py` 加新字段（**注意：与 T-23 互斥**，本批 T-22 先改 config，T-23 顶层重构 admin emails 时 rebase 拿到 SMTP 字段）
  - 新 test 文件 / `.env.example` / `requirements.txt`（追加，不改既有依赖版本）
- **依赖**：✅ T-16 已合（webhook handler 矩阵 + Subscription 模型）；✅ T-11 已合（subscriptions / users.email）
- **烟测**：
  - 单元：渲染 PDF + 字节断言 + dispatch handler smtp mock
  - 集成（可选）：本地 mailpit / smtp4dev 跑一次端到端
- **不做**：自动跨月 cron 触发（v1 只在 stripe 真触发 invoice.paid 时发，自然月月底 stripe 会自己触发）；HTML 邮件（先纯文本 + 附件 PDF）

### Track-23 · L-13 ADMIN_EMAILS 迁回 Settings ★ (0.5 天)

- **分支**：`track-23-admin-emails-settings`
- **目标**：T-10/14/18 都通过 `os.environ.get("ADMIN_EMAILS", "")` 直读，把它正式落到 `app/config.py::Settings`，避免散落各处 + IDE 提示
- **修改文件**：
  - `fliki-clone-api/app/config.py`：加 `admin_emails: str = "demo@example.com"` 字段（pydantic-settings 会自动从 env `ADMIN_EMAILS` 读；逗号分隔）
  - `fliki-clone-api/app/routers/admin_flags.py`：`_allowed_admins()` 改成读 `get_settings().admin_emails`，按逗号 split + lower；保留行为兼容（demo@example.com fallback）
  - `fliki-clone-api/.env.example`：加 `ADMIN_EMAILS=demo@example.com,you@example.com` 说明
  - 新 `fliki-clone-api/tests/test_track23_admin_emails.py` 4+ case：缺 env 走 fallback / env 单 / env 多逗号 / 与 `_is_admin_email` 联动正确
- **互斥锁（独占）**：
  - `app/config.py` 加新字段（**与 T-22 同时改 config.py**：T-22 加 SMTP\_\* 字段；本批默认 T-22 先合，T-23 拿到 main 后再合，避免冲突。**协调者合并顺序：T-22 → T-23**）
  - `routers/admin_flags.py::_allowed_admins` 函数体（小段独占）
  - `.env.example`
- **依赖**：✅ T-10 / T-14 / T-18 已合（这些 Track 只 _读_ `os.environ`，本 Track 把读源切到 settings 不会破坏行为）
- **烟测**：单元测试 + 跑全量 pytest 验证 T-10/14/18 既有 89 case 仍 PASS（关键：`_require_admin` 在 fixture 里走的是 `_is_admin_email("demo@example.com")` → 经 settings.admin_emails 默认值仍命中）
- **不做**：admin role 升级（留给 T-24）

### Track-24 · L-05 真 RBAC（workspace member role）★ (1.5 天) ⏸ **待 T-23 合并后再派**

- **分支**：`track-24-rbac-workspace-role`（**等 T-23 合到 main 后由协调者创建**）
- **依赖**：✅ T-23 必须先合（保证 `_is_admin_email` 已切到 settings；本 Track 在 settings 字段基础上扩展）
- **目标**：把 admin 邮箱白名单升级为 workspace member role（`admin` / `editor` / `viewer`）；老 demo@example.com fallback 保留
- **修改文件**（合并后由协调者写卡片完整 specs；下面是初稿）：
  - 新 alembic：`team_members` 加 `role: VARCHAR DEFAULT 'editor'` 列 + backfill workspace owner = `admin`
  - `app/services/auth/rbac.py` 新模块：`get_user_role(user_id, workspace_id) -> "admin"|"editor"|"viewer"|None`；缓存 60s
  - `routers/admin_flags.py::_require_admin` / `routers/cost.py::_resolve_query_tenant` 改用 `rbac.get_user_role(...) == "admin"`，邮箱白名单作为兜底兼容
  - 前端 admin 入口逻辑同步切到从 user role 决定（不只是邮箱）

### Track-25 · L-10 配额超限 SSE 实时推送 ★ (0.5 天)

- **分支**：`track-25-quota-exceeded-sse`
- **目标**：用 T-17 redis Stream 框架推 `quota_exceeded` / `bucket_full` 事件给前端，让用户在「下次跑被拒之前」就看到 toast / 红色徽章，避免突然 402/429 困惑
- **修改文件**：
  - 后端 `fliki-clone-api/app/services/pipeline/quota.py::reserve_tenant`：当 reserved + new > limit 时，**抛 402 之前**调 `events.publish_to_channel("user:{user_id}", "quota_exceeded", {...})`（新 channel 类型，与 pipeline / publish_plan 互不打扰）
  - 后端 `fliki-clone-api/app/services/pipeline/provider_buckets.py::acquire`：当 bucket 满 RATE_LIMITED 时同样推 `bucket_full`
  - 后端 `fliki-clone-api/app/services/pipeline/events.py`：复用既有 `_publish_to_channel` 内核，新加 `publish_user_event` / `subscribe_user`（channel `user:{user_id}`）
  - 后端 `fliki-clone-api/app/routers/pipelines.py`：新加 `GET /api/pipelines/user-events` SSE 端点（owner 鉴权：从 cookie 拿 current_user.id）
  - 前端新 hook `fliki-clone/src/hooks/use-user-events.ts`：subscribe `/pipelines/user-events`；监听 `quota_exceeded` / `bucket_full`；调 `feedback.error` 弹 toast
  - 前端 `app/[locale]/(app)/layout.tsx`（或全局根）挂上 hook，让所有页面都能收到（不用每个页面都订阅）
  - 新 `fliki-clone-api/tests/test_track25_quota_sse.py` 4+ case：reserve 超限抛事件 + bucket 满抛事件 + redis 不可用 noop
- **互斥锁（独占）**：
  - `services/pipeline/quota.py::reserve_tenant` 函数末尾抛事件段
  - `services/pipeline/provider_buckets.py::acquire` 抛事件段
  - `services/pipeline/events.py` 加 `publish_user_event` / `subscribe_user`（不动既有 channel）
  - `routers/pipelines.py` 加 `GET /api/pipelines/user-events` 段
  - 新 hook `use-user-events.ts`
  - `(app)/layout.tsx` 挂载 hook 一行
- **依赖**：✅ T-17 已合（redis Stream 内核）；✅ T-18 已合（quota.reserve_tenant 是 v2）
- **烟测**：
  - 单元：mock redis client 断 publish_user_event 被调 + payload 正确
  - 集成：起 redis → reserve 真超限 → 第二个进程订阅 user channel 应收到事件
- **不做**：前端 toast 节流 / 去重（v1 简单 toast 即可）；不影响 pipeline / publish_plan 既有 SSE

## 2.8 第六波（已全部 merge，留作历史档案）

> **以下 1 条已合并到 main**（见 0.6 表）。新派发请直接看 2.9 节剩余可派任务。

### Track-24 · L-05 真 RBAC（workspace member role）★ (1.5 天)

- **分支**：`track-24-rbac-workspace-role`（已本地预创建在 `8758721` 之后）
- **目标**：把 admin 邮箱白名单升级为 workspace member role（`admin` / `editor` / `viewer`）；T-23 已把 `admin_emails` 落到 `Settings`，本 Track 在其上做 fallback；老 `demo@example.com` 兼容保留
- **修改文件**：
  - **新 alembic** `fliki-clone-api/alembic/versions/20260505_1700_add_team_member_role.py`（rev `d4e5f6a7b8c9` 顶 `c3d4e5f6a7b8`）：`team_members` 加 `role: VARCHAR(20) DEFAULT 'editor'` 列 + 普通索引；一次性 backfill：workspace owner = `admin`（`UPDATE team_members tm SET role='admin' FROM workspaces w WHERE tm.workspace_id=w.id AND tm.user_id=w.owner_id`）；其它行保留 default `editor`
  - `fliki-clone-api/app/models/team.py`（或对应 ORM 模块）：`TeamMember` 加 `role: Mapped[str]`
  - **新模块** `fliki-clone-api/app/services/auth/__init__.py` + `rbac.py`：
    - `get_user_role(user_id, workspace_id) -> "admin"|"editor"|"viewer"|None`
    - `is_admin(user_id, *, workspace_id=None, email=None) -> bool`：先查 team_member.role==admin；workspace_id 缺失时遍历用户所有 workspace 取最高权限；最终 fallback `_is_admin_email(email)`（兼容 demo@example.com）
    - 60s 内存缓存（同 Track-10 `tenant.py` pattern）
  - `fliki-clone-api/app/routers/admin_flags.py::_require_admin`：改用 `rbac.is_admin(current_user.id, email=current_user.email)`，邮箱白名单作为兜底兼容
  - `fliki-clone-api/app/routers/cost.py::_resolve_query_tenant`：admin 判定同样切到 `rbac.is_admin(...)`
  - 前端 `lib/admin-flags.ts::getAdminMe` 返 schema 不变（`is_admin: bool` 仍来自后端 `is_admin(...)` 判定）
  - 新 `fliki-clone-api/tests/test_track24_rbac.py` 8+ case：alembic 列存在 / role default editor / owner backfill 为 admin / get_user_role 三状态 / is_admin 邮箱兜底 / is_admin team_member 命中 / cache TTL 行为 / `_require_admin` 集成
- **互斥锁（独占）**：
  - alembic 槽 rev `d4e5f6a7b8c9`（独占第六波迁移）
  - `models/team.py::TeamMember` 加 `role` 字段（小段独占）
  - 新模块 `services/auth/rbac.py`
  - `routers/admin_flags.py::_require_admin` 函数体（小段独占；T-23 已合，`_is_admin_email` 不变作为兜底）
  - `routers/cost.py::_resolve_query_tenant` 函数体（小段独占；admin 判定切到 rbac）
- **依赖**：✅ T-23 已合（`admin_emails` 在 Settings；`_is_admin_email` 是 fallback 调用方）
- **烟测**：
  - alembic upgrade head + downgrade -1 + upgrade（保证可逆）
  - 单元：rbac.is_admin 三路径（team_member.role / 邮箱白名单 / 都不命中）
  - 集成：seed 一个 user 是 workspace owner → role 自动 backfill 为 admin → `_require_admin` 通过；demo@example.com fallback 不依赖 team_member 仍通过
- **不做**：editor / viewer 实际权限分级（v1 只识别 admin vs 非 admin；编辑权限分级是 L-05 真做时的事）；workspace 切换 UI（前端用第一个有权限的 workspace 即可）

## 2.9 剩余可派任务（v1 工程闭环已收口；以下都是外部依赖 / 商务问题 / 长尾，可任意时机派）

> 见下方 **2.9.1 第七波** —— 5 条已派发；以下 3 条仍在等外部 / 商务输入。

### Track-19 · ArtAgent v6 多角色 IP-Adapter 真接入 ★ (1-1.5 天) ⏸ 等外部依赖

- 等 SiliconFlow Kolors-IP / Replicate Flux Redux 出 multi-IP 端点；当前 Track-09 已留 `anchors_by_role` 接入点

### Track-20 · YouTube + Stripe 真账号 e2e（**协调者自跑，不开 Agent**）★★ (半天)

- 不创建 feature branch（不动代码）；交付物：`E2E_VERIFY_REPORT.md`（截图 + log + 通过结论）
- 详细操作清单见 SESSION_HANDOFF.md「T-20 协调者自跑指南」段

### Track-12 · bilibili 自动发布（依赖 MCN 商务入驻）★ (2-3 天)

- 等 MCN OpenAPI；技术骨架已在 `adapters/bilibili.py` 留好

## 2.9.1 第七波 5 Track（已全部 merge，留作历史档案）

> **以下 5 条均已合并到 main**（见 0.7 表）。新派发请回到 §2.9 看剩余 3 条等外部依赖的任务，
> 或从 §3 长尾重新挑（L-12 i18n 仍未做 / L-15 已完成 / L-14 已完成 / L-06 已完成 / L-02 已完成
> / L-07-09 ADR 已完成）。
>
> 历史 spec（保留作 reference，下次类似 Track 派发时复用 互斥锁矩阵 / 文件分区 pattern）：
>


> **协调者注**：先修了 `Makefile::test` target（`pytest` → `.venv/bin/python -m pytest`），
> 让 `make test` 真能 130 PASS（之前走系统 framework pytest 缺 `pytest-asyncio` 插件，
> 55 个 async case 全被误判 sync 失败）。这条不属于任何 Track，已直接合 main。
>
> 第七波从长尾里挑 5 条互斥锁清晰、可并行的：
>
> | Track | 内容 | 工作量 | 互斥锁主战场 |
> |---|---|---|---|
> | 26 (L-02) | 卡拉 OK 字幕高亮 | 半天 | 前端 `pipeline/page.tsx::VoiceArtifact` 段 + 新 hook |
> | 27 (L-14) | RBAC editor/viewer 实际写权限分级 | 1 天 | 后端 router 写端点 Depends 段 + 前端按钮 disable 段 |
> | 28 (L-06) | Celery worker Docker + supervisor | 半天 | 仓库根新 `docker-compose.yml` + Dockerfile + Makefile docker-* target |
> | 29 (L-07+08+09) | 3 个 ADR 文档（凭证 / 发布 SLA / 一致性演进） | 1 天 | 纯新文档（独立） |
> | 30 (L-15) | workspace 切换 UI + 后端 list-my-workspaces 路由 | 半天 | 前端 sidebar **顶部**段 + 新 lib + 新 hook + 后端 `team.py` 加 GET 路由 |
>
> **冲突预警**：T-27 和 T-30 都会动 `sidebar.tsx`，但分区明确：
> - T-30 改的是 sidebar **顶部 logo 之下**（新 `<WorkspaceSelector/>` dropdown）；
>   不动 admin links 段（行 `127-145`）
> - T-27 改的是 admin links 段 + `lib/admin-flags.ts::getAdminMe` schema 扩 `role`
>   字段；不动顶部
>
> 协调者合并顺序建议：T-29（独立文档零冲突）→ T-28（独立 Docker）→ T-26（独立前端 VoiceArtifact）
> → T-30（sidebar 顶部 + lib/workspaces.ts + 后端 team.py）→ T-27（最后合，吸收
> sidebar admin links 段 + admin-flags.ts schema 扩展，与 T-30 sidebar 顶部段
> git auto-merge 应通过）。

### Track-26 · L-02 卡拉 OK 字幕高亮 ★ (半天)

- **分支**：`track-26-karaoke-highlight`（待协调者创建）
- **依赖**：✅ Track-04 (VoiceAgent v4 word-level outputs.subtitles[].words[{start,end,word}] 已落地)
- **目标**：VoiceArtifact 已经渲染出每条字幕的 word 时间轴卡片，但只是静态展示。
  让前端监听 audio 元素的 `timeupdate`，根据当前 `audio.currentTime` 在
  `subtitle.words` 数组中二分查找当前 word index，加 violet bg + scale 动画，
  实现卡拉 OK 视觉效果。
- **修改文件**：
  - **新 hook** `fliki-clone/src/hooks/use-audio-current-word.ts`：
    - 入参：`audioRef: RefObject<HTMLAudioElement>` + `subtitles: Array<{start,end,words?:Array<{start,end,word}>}>`
    - 内部：`useEffect` 注册 `timeupdate` listener（节流 ≤ 33ms / 30fps），
      当前时间二分查找命中的 (subtitleIndex, wordIndex)；返 `{currentSubtitleIndex, currentWordIndex}`
    - 边界：currentTime 在所有 words 之外返 `(-1, -1)`；audio paused 也持续返当前位置
  - `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx::VoiceArtifact`（行号约 1690-1900 段）：
    - audio 元素加 `ref={audioRef}` + `onPlay/onPause` 控制 hook enabled
    - 字幕条循环渲染时（约行 1819-1880）：
      - 字幕 wrapper 加 `data-subtitle-index={i}`；命中 `currentSubtitleIndex` 时整条加 sky-50 bg
      - word span 循环（约行 1854-1862）：命中 `currentWordIndex` 时 word 加 `bg-violet-500 text-white`，
        其它 word 维持原状；用 `transition-colors duration-150` 平滑过渡
    - 顶部状态徽标加一条「卡拉 OK 实时高亮 ✓」（仅 v4 word-level 字幕场景显示）
- **互斥锁（独占）**：
  - 新 hook 文件 `use-audio-current-word.ts`（独占）
  - `pipeline/page.tsx::VoiceArtifact` 段（行 1690-1900；与 ArtArtifact / VideoArtifact / EditArtifact / PlanRow / ProductionPanel / 其它顶层段无冲突）
- **不做**：autoplay / 字幕条点击跳转 audio.currentTime（留给后续 polish）；非 word-level 字幕（v3 行级）的高亮（v3 没 word，没法做卡拉 OK）
- **烟测**：
  - jest/vitest 单测（新 `tests/use-audio-current-word.test.ts`）：构造假 subtitles 数组 + 模拟 audio currentTime 推进 → 断言 currentSubtitleIndex / currentWordIndex 单调推进 + 边界返 -1
  - 手测（不强制）：浏览器拉一个 v4 字幕的 run，点 play 看高亮跟着 audio 走

### Track-27 · L-14 RBAC editor/viewer 实际写权限分级 ★★ (1 天)

- **分支**：`track-27-rbac-editor-viewer`（待协调者创建）
- **依赖**：✅ Track-24 (services/auth/rbac.py + team_members.role 列已落地；本 Track 在其上扩 editor/viewer 语义)
- **目标**：T-24 已经写了 `is_admin(user_id, *, workspace_id, email)`，但全仓库只用了「admin vs 非 admin」二元判断。
  本 Track 把 role 真接到写操作鉴权：admin 可改 billing；admin/editor 可创建/修改/删除 versions/publish_plans + 启 pipeline + 执行 publish；
  viewer 仅读。前端按钮按 role disable + tooltip。
- **修改文件**：
  - **后端** `app/services/auth/rbac.py` 扩展（不动 is_admin / get_user_role 既有签名）：
    - 加 `is_editor(user_id, *, workspace_id=None) -> bool`：role in ("admin", "editor")，命中规则同 is_admin（显式 workspace → 任意 workspace 兜底；**不**走邮箱 fallback，editor 必须真在 team_members）
    - 加 `is_viewer(user_id, *, workspace_id=None) -> bool`：role 非空即 True（admin/editor/viewer 都可读）
    - 加 `require_role(allowed: list[str])` FastAPI Depends factory：返 `Depends(_check)`，未命中抛 403 `{"detail": "需要 admin/editor 权限"}` 等带 role 的中文消息；admin 走 fallback 邮箱白名单仍命中
  - **后端 router 写端点加 Depends**（**不**改既有签名，仅在路由 decorator 加 `dependencies=[require_role(["admin","editor"])]` 或 函数签名最后加 `_=Depends(require_role(...))`）：
    - `routers/production.py`：`POST /publish-plans` / `PATCH /publish-plans/{id}` / `DELETE /publish-plans/{id}` / `POST /publish-plans/{id}/execute` / `POST /versions` / `POST /versions/{id}/publish` / `DELETE /versions/{id}` → require_role(["admin","editor"])
    - `routers/pipelines.py`：`POST /pipelines` (start) / `POST /pipelines/{id}/cancel` / `POST /pipelines/{id}/tick` / `POST /pipelines/{id}/steps/{name}/rerun` / `POST /pipelines/{id}/steps/{name}/approve` → require_role(["admin","editor"])
    - `routers/billing.py`：`POST /billing/checkout-session` / `POST /billing/portal-session` → require_role(["admin"])（计费操作 admin 唯一）
    - `routers/admin_flags.py`：既有 `_require_admin` 已经做这个，确保对齐到新的 require_role(["admin"])（**不**改 _require_admin 内部，让既有 7 case 保持 PASS）
  - **后端** 新 `app/routers/auth.py` 加（或扩既有 me 端点）：`GET /me/role?workspace_id=` → 返 `{role: "admin"|"editor"|"viewer"|null, is_admin, is_editor, is_viewer, email}`，让前端能批量探测
  - **前端** `lib/admin-flags.ts::AdminMeOut` 扩 schema：加 `role: string|null` / `is_editor: boolean` / `is_viewer: boolean`（与后端 GET /admin/feature-flags/me 保持兼容；后端 admin_flags.py /me 也要顺手加这三字段）
  - **前端** 新 `lib/role.ts` + `use-current-role.ts`：薄封装 admin-flags.getAdminMe；export `useCurrentRole(): {role, isAdmin, isEditor, isViewer, loading}`
  - **前端按钮 disable**（按 role 灰化 + tooltip "需要 admin/editor 权限"）：
    - `pipeline/page.tsx::ProductionPanel` 内的「另存为版本」/「新建发布计划」/「删除」按钮 → viewer disable
    - `pipeline/page.tsx::PlanRow` 的「执行」按钮 → viewer disable
    - `pipeline/page.tsx` 顶部「启动」按钮 → viewer disable
    - 新 `app/billing/page.tsx::UpgradeButton` → 非 admin disable
- **互斥锁（独占）**：
  - 后端：`services/auth/rbac.py` 末尾加新函数（不改既有签名）；4 个 router 写端点 decorator 加 dependencies；新 `routers/auth.py::GET /me/role`（如果 routers/auth.py 太大新建 `routers/me.py` 也行）；`routers/admin_flags.py::/me` 端点 schema 扩三字段
  - 前端：`lib/admin-flags.ts::AdminMeOut` schema 扩三字段；新 `lib/role.ts` + `use-current-role.ts`；按钮 disable 段（独立控制 disabled prop，不动按钮其它逻辑）
  - **与 T-30 互斥**：T-30 不会动 router 写端点 / role 判定 / admin-flags schema；T-30 只新加 `GET /api/team/workspaces/me` + `lib/workspaces.ts` + sidebar 顶部段。两者并行不冲突。
- **不做**：role 编辑 UI（admin 改 member.role 已经在 `routers/team.py::PATCH /team/members/{id}` 里，不动）；workspace 切换让 role 跟着 workspace 切（让 T-30 落 workspace 选择后再做联动；本批 use-current-role 仅探当前默认 workspace）
- **烟测**：
  - 单元：`tests/test_track27_rbac_role.py`（新文件）覆盖 `is_editor` / `is_viewer` / `require_role` 三函数 ≥ 8 case：viewer 调写端点 403、editor 调 admin-only 端点 403、admin 全通过、邮箱白名单兜底仅对 admin 生效不对 editor、role=None 拒绝
  - 集成：mock `current_user` role=editor → POST /publish-plans 返 200；role=viewer → 403 + detail 含「editor」
  - 跑全量 `make test` 验证既有 130 case 仍 PASS（关键：`_require_admin` 在 fixture 里走的是 `is_admin("demo@example.com", email=...)` → 邮箱白名单 fallback 仍命中）

### Track-28 · L-06 Celery worker Docker + supervisor ★ (半天)

- **分支**：`track-28-celery-docker`（待协调者创建）
- **依赖**：无（独立 ops 工作）
- **目标**：当前 backend / celery worker / 前端都靠手动 `make pipeline-worker` / `npm run dev` 起；
  写一份 `docker-compose.yml` 让单机部署可一键 `docker compose up`：postgres + redis + backend + frontend + celery worker（pipeline 三队列）+ celery beat（如果需要）。
- **修改文件**：
  - **新** `fliki-clone-api/Dockerfile`：
    - 基于 `python:3.10-slim`
    - 装 ffmpeg（apt-get install）+ requirements.txt + requirements-dev.txt
    - WORKDIR /app + COPY app/ alembic/ alembic.ini Makefile
    - 默认 CMD `uvicorn app.main:app --host 0.0.0.0 --port 8000`（不带 --reload）
  - **新** `fliki-clone/Dockerfile`：
    - 基于 `node:20-alpine`
    - 装 deps + COPY src/ public/ next.config.* tsconfig.json
    - `npm run build` + 默认 CMD `npm run start`
  - **新** `docker-compose.yml`（仓库根，与 fliki-clone-api 同级）：
    ```yaml
    services:
      postgres: image postgres:15 + healthcheck pg_isready
      redis:    image redis:7-alpine + healthcheck redis-cli ping
      backend:  build ./fliki-clone-api + depends_on postgres+redis healthy + env DATABASE_URL_SYNC / CELERY_BROKER_URL / SILICONFLOW_API_KEY 等从 .env 透传 + restart unless-stopped
      worker:   build ./fliki-clone-api + command celery -A app.services.pipeline.celery_app worker -Q interactive,media,default --concurrency=2 --loglevel=info + depends_on backend healthy + restart unless-stopped
      frontend: build ./fliki-clone + depends_on backend healthy + env NEXT_PUBLIC_API_URL=http://backend:8000 + restart unless-stopped
    volumes:
      postgres_data:
    ```
  - **新** `.dockerignore`（仓库根）：忽略 .venv / node_modules / .git / .env / __pycache__ 等
  - `Makefile`（fliki-clone-api 内）末尾加：`docker-up`（从仓库根调 docker compose up）/ `docker-down` / `docker-logs` / `docker-rebuild` target
  - **新** `docs/deployment.md`：单机 docker 部署快速指南（前置：装 docker / .env 配关键 key / `docker compose up -d` / 端到端验证）
- **互斥锁（独占）**：
  - 新 Dockerfile × 2（独占）
  - 新 docker-compose.yml（独占）
  - 新 .dockerignore（独占）
  - Makefile 末尾追加 docker-* target（与既有 test target 不冲突；T-29 改的是 docs/，与本 Track 不冲突）
  - 新 docs/deployment.md（独占）
- **不做**：k8s helm chart（出生产部署再说）；secrets 管理（.env 直接 mount，生产用 docker secret 留待真上线）；CI 跑 docker build（CI 一起做）；postgres data 持久化高级配置（默认 named volume 够用）
- **烟测**：
  - `docker compose config` 验证 yaml 合法
  - `docker compose build` 至少完成（不需要真 up，本地 docker 起 PG 5 分钟太慢）
  - 写 NOTES 时附 `docker compose config` 输出片段证明合法

### Track-29 · L-07+08+09 ADR 文档三连 ★ (1 天)

- **分支**：`track-29-adr-docs`（待协调者创建）
- **依赖**：无（纯文档）
- **目标**：把 v1 收口前的几个关键工程决策固化成 ADR：凭证加密 / 多平台发布 SLA / 角色一致性演进。后续做改动有 reference。
- **修改文件**（**全部新文件，零冲突**）：
  - **新** `fliki-clone-api/docs/adr/003-credentials-encryption.md`：
    - 标题：「ADR-003：发布平台凭证加密策略」
    - Context：Track-01 落 Fernet 加密；KEY 缺失时降级 plain text + warning
    - Decision：单 Fernet KEY（`PUBLISH_CREDENTIAL_FERNET_KEY` env）；KEY 缺失静默 plain text + log warning（dev 友好）；future rotation 走多 KEY 兼容（`MultiFernet`）
    - Alternatives：KMS（生产部署再考虑；本地开发依赖太重）/ AES-GCM 自签 nonce（reinvent）/ 不加密（v0 状态）
    - Consequences：dev 不需要任何配置；prod 上线必须配 KEY；rotation 时新加 KEY 到列表头继续解旧密文
    - 引用：`app/services/publishing/credentials.py` / `scripts/migrate_encrypt_creds.py`
  - **新** `fliki-clone-api/docs/adr/004-multi-platform-publish-sla.md`：
    - 标题：「ADR-004：多平台发布执行器 SLA 与重试策略」
    - Context：Track-02/03/13/15 共同搭出的 publish 执行器；YouTube 真发 chunked PUT + DLQ 路由
    - Decision 矩阵（每平台一段）：
      - dry_run：始终启用 100% SLA；返 mock external_id；不入 DLQ
      - youtube：8 MiB chunked PUT + 单片 5xx/408/429 指数退避 1s/2s/4s 最多 3 次；4xx 立即抛 PublishError 入 DLQ；安全闸门 confirm_real_publish=false 拒绝真发；DLQ retry 通过 task_name 路由回 execute_publish_plan_task
      - bilibili：v1 stub（无 OpenAPI），引导手动上传，不入 DLQ；待 MCN 入驻补真适配
    - 重试策略：DLQ 仅 pending 可 retry；retry 走 `_retry_dispatch` 按 task_name 分发；celery 模式走 `execute_publish_plan_task.apply_async`，BG 模式走 `_publish_execute_with_events`
    - 凭证生命周期：YouTube OAuth refresh_token 长期有效；access_token 1h 过期，adapter 调用前自动 refresh；refresh 失败抛 PublishError 引导用户重新 OAuth
    - Consequences：未来加 TikTok / Instagram 走同 protocol；SLA 矩阵跟着加一行
  - **新** `fliki-clone-api/docs/adr/005-character-consistency-evolution.md`：
    - 标题：「ADR-005：ArtAgent 角色一致性 v3 → v4 → v5 → LoRA 演进」
    - Context：v2 每镜独立出图，主角形象漂移；引入 v3 prompt-only / v4 IP-Adapter / v5 多角色 anchor + canary（Track-09/10）
    - Decision：演进三阶段
      - v3（已落）：`_inject_consistency_into_shots` 把 `[Consistent character: protagonist=...]` 注入 enhanced_prompt；negative_prompt 加防漂关键词
      - v4（已落）：`character_anchor.url` 喂 image provider（IP-Adapter）；不支持时剥离 `image_url` 重试同模型
      - v5（已落）：每个 character_card 各一份 anchor + 按 `shot.focus_character` 逐镜选；canary feature_flag 染色 v4 ↔ v3-prompt-only
      - v6（外部依赖待启）：等 SiliconFlow Kolors-IP / Replicate Flux Redux 真 multi-IP 端点；当前 anchors_by_role 接入点已留
      - 远期（M+）：训练每角色 LoRA（用 anchor 做训练集 1k+ 样本）；LoRA 权重存 `character_cards.lora_weight_url`；inference 时按 focus_character 切 LoRA
    - Tradeoffs：Prompt 注入（便宜 / 漂移大）vs IP-Adapter（中等 / 单角色稳）vs LoRA（贵一次 / 多角色稳 / 需训练数据）
    - Consequences：当前 v5 是商业可用基线；v6 接入待外部；LoRA 是远期路线，工程预留 `character_cards` 表 schema
- **互斥锁（独占）**：
  - 全部新文件，零冲突
- **不做**：改 docs/adr/001-002（已落地不动）；改任何业务代码
- **烟测**：
  - `markdownlint docs/adr/00[3-5]-*.md`（如果仓库有 lint 配置）；否则手测每文件 `head -10` 确认有标题/Context/Decision/Consequences 四段

### Track-30 · L-15 workspace 切换 UI + 后端 list-my-workspaces 路由 ★ (半天)

- **分支**：`track-30-workspace-switcher`（待协调者创建）
- **依赖**：✅ Track-24（rbac.get_user_role 已落地，本 Track 复用）
- **目标**：当前所有 user 默认走 `_get_or_create_workspace(user.id)` 拿到 own workspace；user 在多个 workspace
  里时只能用第一个有权限的，没法显式切。本 Track 加：(1) 后端 `GET /api/team/workspaces/me` 列当前 user 所有
  workspace + 每个 role；(2) 前端 sidebar 顶部 workspace selector dropdown + Context Provider 全局可用；(3) 切换后
  把 workspace_id 存 localStorage + Cookie（或 query param）让后端读 workspace 上下文。
- **修改文件**：
  - **后端** `routers/team.py` 加 `GET /api/team/workspaces/me`：返 `{workspaces: [{id, name, role, is_owner, created_at}]}`，
    用 `team_members LEFT JOIN workspaces` 拉当前 user 在的所有 workspace + 自己 own 的（owner 没 team_members 行也要算 admin）。
    复用 `app.services.auth.rbac.get_user_role` 拿 role；owner 自动 role=admin（与 T-24 backfill 一致）
  - **前端** 新 `lib/workspaces.ts`：
    - 类型 `WorkspaceMembership { id, name, role, is_owner, created_at }`
    - `listMyWorkspaces() -> Promise<{workspaces: WorkspaceMembership[]}>` 调 GET /api/team/workspaces/me
  - **前端** 新 `hooks/use-current-workspace.ts`：
    - Context Provider `<WorkspaceProvider>` 包子树
    - `useCurrentWorkspace()` 返 `{current, list, switch(id), loading, refresh}`
    - localStorage key `fliki:current-workspace-id` 持久化；首次加载时 = 列表第一个
    - 切换时 setState + write localStorage + 触发 query refetch（可选 emit 自定义事件让 SSE / queries 知道）
  - **前端** `app/[locale]/(app)/layout.tsx`：把 `<WorkspaceProvider>` 包在 `<UserEventsListener>` 之外（最外层），让 sidebar / 子页面都能用
  - **前端** `components/app-shell/sidebar.tsx`：在顶部 logo 之下（行 100-106 段下方）加 `<WorkspaceSelector />` —— shadcn `<Select>` 或自定义 dropdown，列 workspaces + 当前选中 + role badge（admin 紫 / editor sky / viewer slate）
  - **新** `components/app-shell/workspace-selector.tsx`：薄封装 useCurrentWorkspace + dropdown UI
- **互斥锁（独占）**：
  - 后端 `routers/team.py` 末尾加新路由（不改既有 4 端点）
  - 前端新文件：lib/workspaces.ts / hooks/use-current-workspace.ts / components/app-shell/workspace-selector.tsx
  - `(app)/layout.tsx` 加 Provider wrap（小段独占；T-25 加的 UserEventsListener 不动；本 Track 把 Provider 作为最外层）
  - `components/app-shell/sidebar.tsx`：仅顶部段（行 100-106 之间插入 WorkspaceSelector）；**不动** admin links 段（行 127-145）让 T-27 安全
- **不做**：workspace 切换后所有 queries 的真实 invalidate（让 hook emit 事件，page 自己监听；本批不强制每页改）；workspace 创建 / 删除 UI（已有 settings/team 入口）；多租户隔离的真 API guard（_get_or_create_workspace 仍按 owner 兜底，不本批改）
- **烟测**：
  - 后端单元（新 `tests/test_track30_workspaces.py`）：seed 1 user own 1 workspace + member 另 1 workspace → GET /api/team/workspaces/me 应返 2 条，own 的 role=admin（owner 兜底）/ member 的 role=team_members 真值
  - 前端：手测打开 sidebar 看 selector 渲染；切换不报错；localStorage 写入正确 key

## 3. 长尾（任意时机）

| ID | 任务 | 工作量 |
|---|---|---|
| L-01 | 字幕翻译 + 多语言版本 | 1 天 |
| ~~L-02~~ → T-26 | ~~卡拉 OK 高亮联动 audio.timeupdate~~ → 第七波派发中 | ~~半天~~ |
| ~~L-03~~ → T-21 | ~~metric dashboard 时序~~ → 第五波已 done | ~~1.5 天~~ |
| ~~L-04~~ → T-22 | ~~月账单 PDF + 邮件~~ → 第五波已 done | ~~1 天~~ |
| ~~L-05~~ → T-24 | ~~RBAC workspace member~~ → 第六波已 done | ~~1.5 天~~ |
| ~~L-06~~ → T-28 | ~~Celery worker Docker + supervisor~~ → 第七波派发中 | ~~半天~~ |
| ~~L-07~~ → T-29 | ~~ADR-003 凭证加密策略~~ → 第七波派发中（合 T-29 三连）| ~~0.5 天~~ |
| ~~L-08~~ → T-29 | ~~ADR-004 多平台发布 SLA~~ → 第七波派发中（合 T-29 三连）| ~~0.5 天~~ |
| ~~L-09~~ → T-29 | ~~ADR-005 角色一致性 v3→v4→v5→LoRA 演进~~ → 第七波派发中（合 T-29 三连）| ~~0.5 天~~ |
| ~~L-10~~ → T-25 | ~~配额超限 SSE 实时推送~~ → 第五波已 done | ~~半天~~ |
| ~~L-11~~ → T-18 | ~~model_calls 加 tenant_id~~ → 第四波已 done | ~~半天~~ |
| L-12 | 前端 i18n 完整覆盖 | 1.5 天 |
| ~~L-13~~ → T-23 | ~~ADMIN_EMAILS 迁 Settings~~ → 第五波已 done | ~~0.5 天~~ |
| ~~L-14~~ → T-27 | ~~RBAC editor/viewer 实际权限分级（T-24 follow-up）~~ → 第七波派发中 | ~~1 天~~ |
| ~~L-15~~ → T-30 | ~~workspace 切换 UI（让 user 显式选 workspace）~~ → 第七波派发中 | ~~半天~~ |

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
