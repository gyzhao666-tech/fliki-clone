# 多 Agent 并行 Backlog（2026-05-05 起；第一波 7 Track + 第二波 4 Track 全部已合并）

> 这份是**给每个 Cursor Agent Window 看的**：进入仓库第一件事 read 这份，找你的 Track，按规则执行。
> 协调者：人类（用户）；分支合并、SESSION_HANDOFF.md 更新由人类（或最后一个 agent）统一负责。

## 0. 仓库 / 进程现状（2026-05-05 13:55 更新）

- **GitHub**：https://github.com/gyzhao666-tech/fliki-clone（monorepo：`fliki-clone-api/` + `fliki-clone/`）
- **本地仓库根**：`/Users/zhaoguangyuan/project/empty/`
- **基线**：`main` @ `f8f8933 Merge track-10-canary-flags`（第二波最后一条）
- **alembic head**：**`a1b2c3d4e5f6`**（含 `feature_flags` 表；已落 DB；不要重复跑）
- **后端进程**：pid `30876`，监听 `127.0.0.1:8000`（无 proxy 污染）；
  **第二波合并后这个 pid 还没重启 → 必须 kill + 重启才会加载新代码**：
  ```bash
  kill 30876
  cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
  **不要带 `--reload`**（会启 Python 3.12 子进程，import error）
- **前端进程**：pid `8947`，3000 端口；hot-reload 自动生效不用重启
- **测试基线**：`cd fliki-clone-api && make test` 应得 **41 passed**；改完代码前后都跑一遍
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

## 1. 通用规则（所有 agent 必须遵守）

1. **每个 Track 一条 feature branch**（已预创建）；进入工作前：
   ```bash
   git checkout track-XX-<your-track>
   ```
2. **不要切换分支**；不要 rebase / merge main；改完留 commit 在 feature branch 上，由人类合并。
3. **alembic 互斥锁**：只有 Track-02 的 agent 可以加新 alembic migration。其他 Track**禁止**改 schema；
   需要新字段时优先用 `meta_json` / `outputs_json` 等已有 JSON 列承载。
4. **`.env` 互斥锁**：只有 Track-01 的 agent 可以改 `.env` / `app/config.py`（追加新 settings 字段）。
5. **`pipeline/page.tsx` 大文件分段**：见每个 Track 注明的具体 panel/section，不要越界。
6. **commit message 风格**：参考 baseline；中英混合 OK；要写**为什么**（why）而非只列 what。
7. **完成后写一份 `TRACK_<ID>_NOTES.md` 在仓库根**：包含：
   - 改了哪些文件 + 为什么
   - 烟测命令 + 结果
   - 已知边界 / 跳过的子任务
   - 后续 follow-up
8. **不要更新 `SESSION_HANDOFF.md`**（最后由人类统一）。
9. **不要 push 到 remote**（用户没说要 push；本地分支即可）。
10. **不要 `git config --global`**；commit 用 `-c user.name=... -c user.email=...` 即可。
11. **沙盒里 backend 启动会被注入 HTTP_PROXY**（向 SiliconFlow 真发会失败 403）；如果你的烟测要真发外部 API，
    用 `required_permissions: ["all"]` 跑；**算法测 / 单元测可以 mock gateway**避免网络。
12. **写完跑一遍 ReadLints / 看 import 路径**；**不要留 ad-hoc smoke 脚本**（用 pytest 或者跑完即删）。


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

## 2.5 第三波候选（建议下次派发）

| 优先级 | Track ID | 内容 | 工作量 |
|---|---|---|---|
| ★★ | T-13 | YouTube chunked PUT + 真账号 e2e（替换 resumable upload；avoid 1080p timeout；进度回写 `plan.meta_json.upload_progress`） | 半天 |
| ★ | T-14 | 前端 Admin · Feature Flags 管理面板（settings 加 tab；列 tenant 全部 flag + 滑块改 pct + Apply；audit log 展示） | 1 天 |
| ★ | T-15 | DLQ retry 识别 `task_name="publish.execute_plan"` 改派 `execute_publish_plan_task.delay` | 1-2 小时 |
| ★ | T-16 | Stripe webhook 单元测试 + `charge.refunded` 退款事件处理 | 半天 |
| ★ | T-17 | SSE 断网重连 `last_event_id`（pipeline + publish 两条流） | 半天 |
| ★ | T-18 | model_calls 加 tenant_id + 按 tenant 聚合（L-11 升优） | 半天 |
| ★ | T-19 | ArtAgent v6 多角色 IP-Adapter 真接入（等 Kolors-IP / Flux Redux multi-IP 端点） | 1-1.5 天 |

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
