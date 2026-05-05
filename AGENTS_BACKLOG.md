# 多 Agent 并行 Backlog（2026-05-05 11:35 起）

> 这份是**给每个 Cursor Agent Window 看的**：进入仓库第一件事 read 这份，找你的 Track，按规则执行。
> 协调者：人类（用户）；分支合并、SESSION_HANDOFF.md 更新由人类（或最后一个 agent）统一负责。

## 0. 仓库 / 进程现状

- **仓库根**：`/Users/zhaoguangyuan/project/empty/`（monorepo：`fliki-clone-api/` + `fliki-clone/`）
- **基线**：`main` @ `786462b chore: initial monorepo baseline`
- **alembic head**：`8b1f6c2d4a93`（已落库；不要重复跑迁移）
- **后端进程**：pid `59135`，监听 `127.0.0.1:8000`（无 proxy 污染）；改后端代码后**手动重启**：
  ```bash
  cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
    .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```
  **不要带 `--reload`**（会启 Python 3.12 子进程，import error）
- **前端进程**：pid `5186`，3000 端口；hot-reload 自动生效不用重启
- **背景知识必读**：`SESSION_HANDOFF.md`（项目当前能力 / 已知坑 / 配置约束）

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

## 2. Track 卡片

> 每个卡片格式：**目标 / 范围 / 修改文件 / 互斥锁 / 依赖 / 烟测 / 不做**
> 8 条 Track 之间**没有共享文件**（除了 `pipeline/page.tsx` 但每个 Track 限定不同 section），可以同时派发。
> Track-03 / Track-09 标了「依赖 X」表示等 X 完成 merge 后再启动那个 agent。

---

### Track-01 · 凭证 Fernet 加密 ★★★ (半天)

- **分支**：`track-01-credentials-fernet`
- **目标**：`platform_credentials.access_token / refresh_token` 当前 plain text；用 Fernet 对称加密落库 + 读时透明解密；现有数据一次性升级。
- **修改文件**：
  - `fliki-clone-api/.env`（追加 `PUBLISH_CREDENTIAL_FERNET_KEY=`；用 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成）
  - `fliki-clone-api/app/config.py`（加 `publish_credential_fernet_key: str = ""`；validator 校验非空时是 32-byte base64）
  - `fliki-clone-api/app/services/publishing/credentials.py`（写库前 `_encrypt(token)`；读出后 `_decrypt(token)`；KEY 缺失时 fallback plain text + 启动时 logger.warning）
  - 一次性脚本 `fliki-clone-api/scripts/migrate_encrypt_creds.py`（把已有 plain text 行升级；幂等）
  - `fliki-clone-api/requirements.txt` 加 `cryptography>=41`（很可能已经有，先 grep 再决定）
- **互斥锁（独占）**：`.env`、`app/config.py`、`credentials.py`、`requirements.txt`
- **依赖**：无
- **烟测**：
  - 重启 backend；OAuth 流程未改，但落库 token 应是 base64 密文（直接 `psql` 看 `platform_credentials.access_token` 应该是 `gAAAAA...`）
  - 旧 plain text 行用 migrate script 升级
  - revoke 后 row 消失
- **不做**：alembic schema 改动、新加表、改 publishing/executor.py 业务逻辑

---

### Track-02 · YouTube 真发安全闸门 + 前端开关 ★★★ (半天)

- **分支**：`track-02-youtube-confirm-real`
- **目标**：把 v1 隐藏在 `meta_json.confirm_real_publish` 的安全闸门提到独立列；前端 PlanRow 加 toggle。
- **修改文件**：
  - **新 alembic migration**（**只此 Track 占用迁移槽**）：`publish_plans.confirm_real_publish: bool default false`；revision id 自定（建议 `9c2d4e5f6a7b` 或类似）；下一 head 顶上 `8b1f6c2d4a93`。
  - `fliki-clone-api/app/models/production.py`（PublishPlan 加列）
  - `fliki-clone-api/app/services/publishing/adapters/youtube.py`（读 `req.credential.plan_meta` 改成读 plan.confirm_real_publish；executor 把这个字段透传）
  - `fliki-clone-api/app/services/publishing/executor.py::_load_plan` SELECT 加该列
  - `fliki-clone-api/app/routers/production.py`（PublishPlanOut + PublishPlanPatch 加 `confirm_real_publish` 字段）
  - `fliki-clone/src/lib/production.ts`（PublishPlanOut + PatchPublishPlanPayload 加该字段）
  - `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx`：**只改 `PlanRow` 函数**（在 status select 旁加一个 checkbox「真发」+ `<Upload>` 按钮按 confirm 状态变红/绿）
- **互斥锁（独占）**：alembic、`adapters/youtube.py`、`executor.py`、`pipeline/page.tsx::PlanRow`
- **依赖**：无
- **烟测**：
  - `cd fliki-clone-api && .venv/bin/python -m alembic upgrade head` 不报错
  - 重启 backend
  - 创建 youtube plan，confirm=false 时 execute → 走「假发」路径返 mock external_id
  - confirm=true 时 + 真 OAuth 凭证 → 真打 youtube upload；无凭证仍返清晰错误
- **不做**：YouTube resumable upload（chunked PUT）；那是 Track 后续二期

---

### Track-03 · publish 任务异步化（celery + SSE） ★★ (半天)

- **分支**：`track-03-publish-async-celery`
- **依赖**：⚠️ **Track-02 先 merge** —— 因为都改 `production.py` 同一段；Track-03 agent 启动前先 `git merge track-02-youtube-confirm-real`。
- **目标**：当前 `/publish-plans/{id}/execute` 同步等 30-60s；改成入 Celery 即返 202 + SSE 推 plan_state。
- **修改文件**：
  - `fliki-clone-api/app/services/pipeline/tasks.py`（新增 `execute_publish_plan_task` 绑 DLQAwareTask base）
  - `fliki-clone-api/app/services/pipeline/celery_app.py`（路由到 default 队列）
  - `fliki-clone-api/app/routers/production.py`（端点改：默认派发 + 202；保留 `?sync=true` 兜底）
  - `fliki-clone-api/app/services/pipeline/events.py`（加 `publish_plan_state` 事件类型 + 新通道 `publish:plan:{id}`）
  - `fliki-clone/src/hooks/use-publish-plan-stream.ts`（新 hook：EventSource 拉 `/api/production/publish-plans/{id}/events`；polling fallback）
  - `fliki-clone/src/app/.../pipeline/page.tsx::PlanRow`（点 Upload 后 hook 订阅，loading 转圈直到 published / failed）
- **互斥锁（独占）**：`tasks.py`、`celery_app.py`、`production.py`（与 Track-02 错峰）、`pipeline/page.tsx::PlanRow`（与 Track-02 错峰）
- **烟测**：
  - 起 redis + celery worker（`make pipeline-worker`，`.env` `CELERY_ENABLED=true`）
  - 调 execute → 立即返 202 + plan_id
  - SSE 拉到 `publish_plan_state` 事件 → status 从 draft → running → published
- **不做**：alembic schema 改

---

### Track-04 · ArtAgent v4 IP-Adapter 真接入 ★★ (1 天)

- **分支**：`track-04-art-ipadapter`
- **目标**：v3 已生成 `outputs.character_anchor.url`；v4 把它喂回 image provider 作为 IP-Adapter 参考图，让每镜关键帧主角真锁定。
- **修改文件**：
  - `fliki-clone-api/app/services/model_gateway/providers/siliconflow_image.py`（params 加 `image_url` 透传；如果 SiliconFlow 有 Kolors-IP 端点就路由到它，否则走通用 `/images/generations` 加 image_url 参数；没生效就降级 v3 行为 + degrade warning）
  - `fliki-clone-api/app/services/pipeline/agents/art.py::_generate_keyframes`：读 ctx 里的 character_anchor URL（从 outputs.character_anchor.url 读，因为 anchor 在前面已生成）；对 character_locked=true 的镜传 image_url；非主角镜不传
  - `fliki-clone-api/app/services/model_gateway/types.py`：`RenderRequest.params` 文档加 `image_url` 字段说明
  - 前端 `pipeline/page.tsx::ArtArtifact` 的 shots 网格 🔒 角标右侧加 「IP」二级徽标（character_locked + 真传了 image_url 时显示）；后端 outputs 每镜加 `ip_adapter_used: bool` 字段让前端判断
- **互斥锁（独占）**：`siliconflow_image.py`、`agents/art.py`、`pipeline/page.tsx::ArtArtifact`
- **依赖**：无（Track-05 也读 anchor URL 但改 video.py，不冲突）
- **烟测**：
  - 跑一次 video_full（OPENAI_API_KEY 不要求；跑 art 步骤即可）
  - shots 表每行 `meta_json.ip_adapter_used=true`（主角镜）
  - 主角脸跨镜对比明显比 v3 prompt-only 更稳
  - 当 SiliconFlow 不支持 image_url 时返 400 / 缺参数；agent 应捕获 + 降级 + 写 keyframe_error
- **不做**：改 video step；改 schema

---

### Track-05 · VideoAgent v2：用 anchor 作 IMAGE_TO_VIDEO 主参考帧 ★ (半天)

- **分支**：`track-05-video-anchor-ref`
- **目标**：当前 i2v 用 `shots[i].keyframe_url`；v2：character_locked=true 的镜优先用 `outputs.art.character_anchor.url`，否则用 keyframe，否则降级 GENERATE_VIDEO。
- **修改文件**：
  - `fliki-clone-api/app/services/pipeline/agents/video.py`（i2v 入口 ref-image 选择逻辑；新输出每镜 `ref_image_source: 'anchor'/'keyframe'/'none'`）
  - 前端 `pipeline/page.tsx::VideoArtifact`：每镜卡片右上角加 ref-image 来源徽标（emerald「anchor 锚定」/ sky「keyframe」/ muted「无参考」）
- **互斥锁（独占）**：`agents/video.py`、`pipeline/page.tsx::VideoArtifact`
- **依赖**：无（Track-04 跑通后效果更明显，但本逻辑独立）
- **烟测**：
  - 跑 video_full → 每镜输出 `ref_image_source` 正确
  - 主角镜 `ref_image_source=anchor`；多角色镜 `keyframe`
- **不做**：改 art / publishing / schema

---

### Track-06 · faster-whisper 本地 fallback ★★ (半天)

- **分支**：`track-06-faster-whisper-local`
- **目标**：用户没 OPENAI_API_KEY 时，VoiceAgent v4 word-level 也能本地跑。
- **修改文件**：
  - 新 provider：`fliki-clone-api/app/services/model_gateway/providers/faster_whisper_local.py`（懒导入 faster-whisper 包；import error 时 `is_available=False`；输出格式与 OpenAIWhisperProvider 完全一致：`text/duration_s/segments/words`）
  - `fliki-clone-api/app/services/model_gateway/providers/__init__.py`（导出新 provider）
  - `fliki-clone-api/app/services/model_gateway/gateway.py`：ASR 路由改为 `[OPENAI, FASTER_WHISPER_LOCAL, SILICONFLOW]`；`get_gateway()` 注册新 provider
  - `fliki-clone-api/app/services/model_gateway/types.py`：`ProviderName` enum 加 `FASTER_WHISPER_LOCAL = "faster_whisper_local"`
  - `fliki-clone-api/app/services/model_gateway/cost.py`：加 `(FASTER_WHISPER_LOCAL, ASR) = 0.0`（本地 0 成本）
  - `fliki-clone-api/requirements.txt` 加 `faster-whisper>=1.0`（大依赖；标 optional 注释）
- **互斥锁（独占）**：`gateway.py`、`types.py`、`cost.py`、`requirements.txt`、`providers/__init__.py`
- **依赖**：无
- **烟测**：
  - `pip install faster-whisper` → import 成功
  - 跑 voice step → outputs.asr_provider=`faster_whisper_local`
  - 模拟没装（pip uninstall）→ provider.is_available=False，gateway 自动 fallback SiliconFlow（v3 行级）
- **不做**：改 voice agent 算法（word-level 对齐已在 v4 完成）

---

### Track-07 · Pipeline DAG 前端可视化 ★ (1 天，纯前端)

- **分支**：`track-07-pipeline-dag-view`
- **目标**：流水线节点用 react-flow 渲染成 DAG；点节点跳转到对应 step 卡片。
- **修改文件**：
  - `fliki-clone/package.json` 加 `@xyflow/react@^12`
  - 新组件 `fliki-clone/src/components/pipeline/dag-view.tsx`（接 PipelineRun，渲染节点 + 连线 + state 颜色）
  - `fliki-clone/src/app/.../pipeline/page.tsx`：**只在「流水线节点」section 顶部加 view toggle**（列表 / DAG，默认列表，记忆 localStorage `pipeline.view`）；不要碰其他 section
  - 新组件用现有 stepStateTone helper 决定节点颜色
- **互斥锁（独占）**：`pipeline/page.tsx::section[流水线节点]`（只加 toggle 这一处）、`components/pipeline/dag-view.tsx`、`package.json`
- **依赖**：无
- **完全前端**：不需要重启 backend；npm install 后 hot-reload 即可
- **烟测**：
  - npm install 成功
  - 切到 DAG 视图：节点按 depends_on 连线；终态颜色对（succeeded=emerald、awaiting_review=amber、failed=rose）
  - 点节点滚动到对应 step 卡片
- **不做**：改 backend；改其他 panel

---

### Track-08 · pytest 工程化 ★ (1 天)

- **分支**：`track-08-pytest-suite`
- **目标**：把过去几次会话的 ad-hoc smoke（已删）+ 当前模块全部转成 pytest test suite。
- **修改文件**：
  - 新建 `fliki-clone-api/tests/__init__.py` / `conftest.py` / `pytest.ini`（DATABASE_URL 用临时 sqlite 或同一个 PG 库 + 测试 schema）
  - `fliki-clone-api/tests/test_quota_v2.py`：tenant_quota / provider_buckets / 并发竞态 / resolver / gateway rate_limited / gateway user_id fallback
  - `fliki-clone-api/tests/test_voice_v4.py`：v4 算法 5 case + 集成 mock gateway
  - `fliki-clone-api/tests/test_art_v3.py`：v3 helpers + 集成 3 case
  - `fliki-clone-api/tests/test_publishing.py`：dry-run / youtube no-cred / bilibili stub / 重复 execute 拒绝 / 未知平台 fallback
  - `fliki-clone-api/requirements-dev.txt` 加 `pytest`、`pytest-asyncio`、`httpx`（FastAPI test client）
  - `fliki-clone-api/Makefile` 加 `test:` target
  - 标 unit / integration 两组：`@pytest.mark.unit` 不需 DB；`@pytest.mark.integration` 需要 PG
- **互斥锁（独占）**：`tests/` 整个目录、`requirements-dev.txt`、`Makefile`
- **依赖**：无；**但建议晚点跑**（其他 Track merge 后一并测）。或者**先按 main HEAD 写**，其他 Track merge 时各自补对应 case。
- **烟测**：`make test` 全绿
- **不做**：改 app 代码（除非发现 bug，发现也只在 NOTES 标注让协调者决定要不要修）

---

## 3. 第二波（依赖第一波 merge 后启动）

### Track-09 · 多角色锁定（依赖 Track-04）★ (1 天)
- **预创建分支**：`git branch track-09-multi-character main`（合并完 Track-04 后再切过去 + merge）
- 目标：LLM 标了 focus_character != protagonist 时，给该角色单独出锚点 + 注入对应 prompt 前缀

### Track-10 · 灰度发布 / canary（依赖 Track-01）★ (1.5 天)
- 按 tenant_id hash 选模型版本

### Track-11 · Stripe 计费对接（依赖 Track-01）★★ (2 天)
- subscription / plan 升级流程

### Track-12 · bilibili 自动发布（依赖商务入驻）★ (2-3 天)
- 等 MCN OpenAPI

## 4. 长尾（任意时机）

| ID | 任务 | 工作量 |
|---|---|---|
| L-01 | 字幕翻译 + 多语言版本 | 1 天 |
| L-02 | 卡拉 OK 高亮联动 audio.timeupdate | 半天 |
| L-03 | metric dashboard（cost / view_count 时序） | 1.5 天 |
| L-04 | 月账单 PDF 导出 + 邮件 | 1 天 |
| L-05 | RBAC：workspace member editor/viewer 权限 | 1.5 天 |
| L-06 | Celery worker Docker + supervisor | 半天 |
| L-07 | ADR-003 凭证加密策略 | 0.5 天 |
| L-08 | ADR-004 多平台发布 SLA | 0.5 天 |
| L-09 | ADR-005 角色一致性 v3→v4→LoRA 演进 | 0.5 天 |
| L-10 | 配额超限 SSE 实时推送 | 半天 |
| L-11 | model_calls 加 tenant_id + 按 tenant 聚合 | 半天 |
| L-12 | 前端 i18n 完整覆盖 | 1.5 天 |

## 5. 给单个 Cursor Agent Window 的标准开工提示词

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

## 6. 协调者（人类）的合并 checklist

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
