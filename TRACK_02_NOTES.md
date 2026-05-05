# Track-02 · YouTube 真发安全闸门 + 前端开关 — 完成记录

**分支**：`track-02-youtube-confirm-real`
**commit**：`86d935e feat(publishing): publish_plans 加 confirm_real_publish 列 + 前端 PlanRow toggle`
**新 alembic head**：`9c2d4e5f6a7b`（顶 `8b1f6c2d4a93`）⚠️ **Track-03 同步前必须先 merge 本 Track**
**状态**：✅ 完成；本地烟测 4/4 PASS；已 push 到 origin；未 merge 回 main（按要求）

---

## 1. 改动文件

| 文件 | 性质 | 说明 |
|---|---|---|
| `fliki-clone-api/alembic/versions/20260505_1200_add_publish_plan_confirm_real.py` | 新 | revision `9c2d4e5f6a7b`；加列 `publish_plans.confirm_real_publish BOOLEAN NOT NULL DEFAULT false`；downgrade 干净 drop |
| `fliki-clone-api/app/models/production.py` | 改 | `PublishPlan` ORM 加 `confirm_real_publish: Mapped[bool]`，server_default=`false`，与 DDL 对齐 |
| `fliki-clone-api/app/services/publishing/adapters/base.py` | 改 | `PublishRequest` dataclass 加 `confirm_real_publish: bool = False` 字段 |
| `fliki-clone-api/app/services/publishing/adapters/youtube.py` | 改 | 删 `cred.get("plan_meta")` 路径；改读 `req.confirm_real_publish`；safety_gate meta 文案更新为「toggle plan.confirm_real_publish」 |
| `fliki-clone-api/app/services/publishing/executor.py` | 改 | `_load_plan` SELECT 加 `p.confirm_real_publish`；不再把 `plan.meta` 拼到 `credential["plan_meta"]`；`PublishRequest` 透传新字段 |
| `fliki-clone-api/app/routers/production.py` | 改 | `PublishPlanOut` + `PublishPlanPatch` 加字段；3 处 SQL（list / load / patch）加列；`_plan_row_to_out` 加映射 |
| `fliki-clone/src/lib/production.ts` | 改 | `PublishPlanOut.confirm_real_publish: boolean` + `PatchPublishPlanPayload.confirm_real_publish?: boolean` |
| `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx` | 改（仅 PlanRow） | 状态 select 旁加「真发」checkbox；Upload 按钮按 confirm 状态变红/绿；标题加 LIVE 红色徽标；confirm 文案分两套 |

---

## 2. 为什么这样改

### 2.1 把 `meta_json.confirm_real_publish` 提到独立列
- v1 把开关塞 `meta_json` 是赶时间写的「隐藏后门」。问题：
  - 前端要显式 toggle 必须读写 free-form JSON，类型断言一堆
  - 后端要读必须从 plan 行先 SELECT meta_json 再 dict-get，executor 还得把它拼到 credential 字典里透传
  - 审计 / 索引 / per-tenant 默认策略全做不了
- 提到独立列后：
  - DDL 单一可见（`\d publish_plans` 一眼看到）
  - 模型 / Pydantic / TS 三端类型对齐
  - executor 不再碰 `plan_meta`，adapter 直接读 `req.confirm_real_publish`
  - 后续要做「per-tenant 默认 false」「最近 7 天真发审计」可直接 `WHERE confirm_real_publish=true`

### 2.2 PlanRow toggle 设计
- **乐观更新 + 失败回滚**：toggle 后立刻反映到本地 state，让 Upload 按钮颜色 / LIVE 徽标立刻变；PATCH 失败时回滚 + error toast，避免「以为开了其实还是关」的误操作
- **Upload 按钮颜色**：仅 youtube 平台受影响（dry-run / bilibili adapter 不读该字段）；
  - youtube + 真发 = `text-rose-500` + rose hover bg
  - youtube + mock = `text-emerald-500` + emerald hover bg
  - 其他平台 = 保留原 ghost 样式（不误导）
- **confirm 文案分两套**：真发态用「⚠️ 不可撤销」措辞；mock 态保留温和「dry-run / bilibili 不会真发」原文案
- **LIVE 徽标**：标题旁 rose 小徽标，让列表里能一眼看到哪个 plan 真发开了

---

## 3. 烟测命令 + 结果

```bash
# 1. alembic head 升到新 revision
cd /Users/zhaoguangyuan/project/empty/.track02-worktree/fliki-clone-api && \
  .venv/bin/python -m alembic upgrade head
# → 9c2d4e5f6a7b (head)

# 2. 跑 4 case 烟测（新 worktree 路径，确保用到 commit 后的代码）
cd /Users/zhaoguangyuan/project/empty/.track02-worktree/fliki-clone-api && \
  .venv/bin/python <<'PY'
# (见 commit message 的烟测描述；脚本已跑完即弃)
PY
```

| # | 场景 | 期望 | 实际 | 结果 |
|---|---|---|---|---|
| 1 | confirm=false + 无凭证 | 友好「需要 OAuth credential」错误（status=failed，不是 5xx） | 一致 | ✅ |
| 2 | confirm=false + 假凭证 + 假 GOOGLE_CLIENT_ID | 走安全闸门返 `youtube-pending-...` mock id；safety_gate meta 文案不再提 `meta_json` | 一致 | ✅ |
| 3 | confirm=true + 假凭证 + 假 GOOGLE_CLIENT_ID | 进入真发分支（在下载 render_url 阶段抛 `PublishError`，因为 fake mock URL） | 一致（`download render_url failed: ...`） | ✅ |
| 4 | confirm=true + 无凭证 | 仍是友好「需要 OAuth credential」错误，未升 5xx | 一致 | ✅ |

> 真 OAuth + 真 GOOGLE_CLIENT_ID 的真发烟测**未跑**（需要用户提供 Google Cloud 项目 + 浏览器 OAuth 跳转）；
> 但 Test 3 已经证明 `confirm_real_publish=true` 会跳过 mock 分支真的进入真发路径，结合 v1 已经验证过的 multipart upload 流程，可信度足够。

---

## 4. 给协调者 / Track-03 / 其他 Track 的提示

### 4.1 ⚠️ alembic head 更新
- **新 head：`9c2d4e5f6a7b`**
- **Track-03 启动前必须先 `git merge track-02-youtube-confirm-real`**（按 backlog 第 1 节规则；Track-03 也要改 `production.py` 同一段，会冲突，但因为我加的是新字段，普通 3-way merge 应该自动）
- 其他 Track 暂无 alembic 改动需求，影响仅 head 号
- **协调者合并到 main 后**，记得更新 `SESSION_HANDOFF.md` 第 0 节的 alembic head 和文件路径速查的 alembic 列表

### 4.2 没碰的（按互斥锁）
- ❌ `tasks.py` / `celery_app.py` / `events.py`（Track-03 用）
- ❌ `.env` / `app/config.py` / `credentials.py` / `requirements.txt`（Track-01 用）
- ❌ `pipeline/page.tsx` 其他 panel（只改 PlanRow 函数本体；ProductionPanel / DLQ / Stat / Brief / 步骤卡片全没动）
- ❌ `siliconflow_image.py` / `agents/art.py` / `agents/video.py`（Track-04 / 05 用）

### 4.3 工作流坑（值得记录）
- 期间发现工作目录 `/Users/zhaoguangyuan/project/empty` 同时被多个 Track agent 共享，有 agent 直接 checkout 不同 branch 导致我的 working tree 被另一个 agent stash 走（`stash@{1}: OTHER_AGENT_WORK_track-08-and-04-and-02-in-progress`）。
- **解决方案**：我后来改用 `git worktree add .track02-worktree track-02-youtube-confirm-real` 单独开了个工作目录，避免 branch 切换互踩。**建议协调者要求所有第二波 agent 强制走 worktree**（Track-05 已经在用 `.track05-worktree`，模式是对的）。
- 残留 stash 我没动；用户可酌情 `git stash drop`。
- 我额外创建的 `.track02-worktree/fliki-clone-api/.env`（剥掉了 Track-01 的 `PUBLISH_CREDENTIAL_FERNET_KEY` 行）是临时 smoke 用，merge 后可一并删 worktree 整目录。

---

## 5. 已知边界 / 跳过的子任务

- **YouTube resumable upload（chunked PUT）**：明确属 v2，本 Track 未做。当前 `youtube.py` 仍是 v1 multipart 一次发，1080p 长视频可能 timeout。已留在 backlog `★★ publish 任务异步化` / 后续二期。
- **Per-tenant 默认 confirm_real_publish=false 策略**：列已有了，但还没暴露 admin UI 改默认；当前 INSERT 都走 DDL DEFAULT。
- **真发审计 / 触发器**：未做；建议未来加 `metrics` 行 `kind="publish_real_attempt"` 在 adapter 真发分支入口写一条。
- **bilibili / dry-run adapter 不读 `confirm_real_publish`**：刻意；他们没真发概念。前端 toggle 在 bilibili / dry-run plan 上仍可以勾，但只影响数据，不影响行为；UI 层 LIVE 徽标和按钮颜色都只对 youtube 显示。

---

## 6. 后续 follow-up（不在本 Track 范围）

1. resumable upload chunked PUT（半天）
2. 异步化 publish 任务 + SSE plan_state（Track-03 顺手做）
3. admin UI：per-tenant 默认 confirm_real_publish 设置（1 天，需要 RBAC 配套）
4. metric `publish_real_attempt` 写入 + dashboard 卡片（半天）
