# Fliki-Clone × AI 视频 Agent 流水线 开发计划

> 关联仓库：`fliki-clone`（Next.js 前端）、`fliki-clone-api`（FastAPI + PostgreSQL + Celery + R2）
> 关联视图：`canvases/ai-video-agent-workflow.canvas.tsx`
> 文档定位：把现有"场景化 TTS + 模板成片"SaaS 升级为"多 Agent 视频生产系统"的总路线图。
> 命名约定：本文中"流程"指人编排，"技能/Agent"指可被 AI 自动执行的工位。
>
> **跨会话交接看 [`SESSION_HANDOFF.md`](./SESSION_HANDOFF.md)**（每次会话结束更新）；本文件维护长程路线 + 风险登记 + 详细进展轨迹。

---

## 0. 目标与非目标

### 0.1 目标
1. 把核心数据模型从 `Project / Scene` 扩展为支持完整流水线的对象集（Brief / Topic / ShotList / Render / Review / PublishPlan / Metrics）。
2. 引入“模型网关”服务，统一封装文生视频 / 图生视频 / TTS / 图像 / 字幕 / 翻译 / 口型同步等外部模型。
3. 引入显式工作流引擎，让每个 Agent 工位都能独立重跑、回滚、版本化。
4. 建立单次模型调用级的成本预估、预扣额度与并发上限。
5. 提供一个真正的 Pipeline 前端视图，让人可以编排、审批、回看每个 Agent 节点。
6. 建立合规、水印、滥用追踪的最低底线。

### 0.2 非目标
- **不**自研视频生成大模型，只做编排和接入。
- **不**在 v1 内做长视频（>5 分钟）和影视级合成。
- **不**在 v1 内做端到端无人值守批量生产，保留人工审批节点。
- **不**做实时直播流。

### 0.3 关键边界（流程 vs 技能）
- 人保留：选题判断、叙事节奏、审美、平台判断、商业取舍、终审。
- Agent 接管：研究、脚本初稿、分镜、关键帧、镜头生成、配音、字幕、粗剪、多平台改写、数据回收、复盘草稿。

---

## 1. 阶段总览

| 阶段 | 主题 | 周期建议 | 主要交付 |
|---|---|---|---|
| Phase 0 | 基础决策与对齐 | 1 周 | 架构 ADR、数据模型设计、模型选型清单 |
| Phase 1 | 流水线 MVP | 4–6 周 | 数据模型扩展 + 模型网关 + 工作流引擎骨架 + 一条端到端可跑通的 Demo |
| Phase 2 | 质检、版本与成本拦截 | 3–4 周 | 质检 Agent、版本系统、成本预估与配额、失败重试 |
| Phase 3 | 发布、复盘、Metrics | 3 周 | 发布 Agent、Metrics 表、多平台改写、复盘报告 |
| Phase 4 | Pipeline 前端视图 | 3–4 周 | 节点状态、单步重跑、版本切换、审批入口、平台预览 |
| Phase 5 | 合规、水印、滥用治理 | 2 周 | 内容审核 Agent、水印系统、使用日志、黑名单 |
| Phase 6 | 批量化与多模型路由 | 2–3 周 | 队列分级、模型降级、灰度切换、矩阵号 |

> 周期是“专职 1 后端 + 1 前端 + 0.5 全栈/算法”的估计；并行度高时可压缩。

---

## 2. Phase 0：基础决策与对齐

### 2.1 ADR（必须先定）
1. **工作流引擎选型**：Temporal vs Prefect vs 自研 Celery DAG。
   - 默认建议：先用“Celery + 显式 task graph + 状态表”自研轻量层（不引入 Temporal 运维负担），第二阶段再视复杂度迁移。
2. **模型网关运行形态**：作为 `fliki-clone-api` 内部 module，还是独立 Python 服务（gateway-svc）。
   - 默认建议：v1 内部 module，预留接口稳定，v2 拆服务。
3. **资产存储分层**：R2 路径规范 `tenant/project/scene/version/{type}/{filename}`。
4. **Agent 通信方式**：内部 Celery 队列 + 数据库状态机 + Redis 事件广播。
5. **Pipeline 前端定位**：在 `/app/project/[id]/pipeline` 新增视图，与现有 `/app/project/[id]` 共存，老页面降为“快速生成”入口。

### 2.2 模型选型清单（v1 至少各选 1）
| 类型 | 主选 | 备选 |
|---|---|---|
| 文生视频 | 可灵 / Runway Gen-4 | Pika 2.2 |
| 图生视频 | 即梦 / Kling I2V | Runway Image-to-Video |
| 关键帧/角色图 | Flux + Midjourney | 豆包图片 |
| TTS / 声音克隆 | ElevenLabs（已接） | MiniMax Speech / 讯飞 |
| 配乐 | Suno / Udio | 自有素材库 |
| 字幕 / 翻译 | Whisper + GPT-4o | Rask AI |
| 口型同步 | Runway Act-One / HeyGen Lipsync | wav2lip 自部署 |
| 图像/视频审核 | Cloud Vision / 自部署 NSFW + 关键词 | 阿里云内容安全 |

> 选型不做长锁定，所有调用必须经“模型网关”。

### 2.3 数据模型草案
新增表（建议 SQLAlchemy + Alembic 迁移）：
- `briefs`：项目级输入（受众、平台、人设、禁区、商业目标、参考链接）
- `topics`：候选选题
- `shot_lists`：分镜表（属于 project，是 scene 的上层）
- `shots`：单镜头（属于 shot_list，含 prompt、参考、模型偏好、duration、aspect）
- `renders`：每次模型调用的产物（属于 shot 或 audio_track）
- `audio_tracks`：旁白/音乐/音效
- `subtitles`：字幕轨（按语言、按版本）
- `reviews`：质检记录（属于任意中间产物，含问题清单、处置）
- `publish_plans`：发布计划（平台、版本、时间、标题、封面、标签）
- `publishes`：实际发布记录（外部平台 ID、回链）
- `metrics`：发布后的数据（按平台、时间窗）
- `model_calls`：每次外部模型调用的账单（成本、用时、状态）
- `model_quotas`：租户/项目级配额与并发
- `versions`：跨表通用版本对象（`entity_type`, `entity_id`, `version`, `parent_id`）

保留并扩展：
- `projects`：增加 `pipeline_state`, `current_brief_id`, `default_publish_targets`
- `scenes`：保留作为“快速生成模式”入口，**不再**承担分镜职责
- `characters`：扩展为“角色卡”，含 `reference_assets[]`, `style_board_id`, `voice_id`, `prompt_template`
- `assets`：增加 `source`, `license`, `derivation_chain`

---

## 3. Phase 1：流水线 MVP（最关键阶段）

> 目标：跑通一条端到端的 Demo——从 Brief 输入到一段 30 秒成片，经过研究→脚本→分镜→图→镜头→配音→粗剪→人工审批→导出。

### 3.1 后端任务

#### 3.1.1 数据模型与迁移
- [ ] B1 建立上述新增表的 ORM 与 Alembic 迁移
- [ ] B2 引入 `versions` 通用版本表与 `parent_id` 链
- [ ] B3 编写 seed 数据（一个示例 Brief、一个示例 Topic、一个 ShotList）

#### 3.1.2 模型网关（`app/services/model_gateway/`）
- [ ] B4 定义统一接口：`generate_video(spec) / generate_image(spec) / tts(spec) / asr(spec) / lipsync(spec) / translate(spec)`
- [ ] B5 每个模型一个 `provider`（runway/kling/pika/elevenlabs/...），统一返回 `RenderResult { url, cost, duration_ms, model, version }`
- [ ] B6 加入：超时、退避、限流（令牌桶/leaky bucket）、降级（同类备选）
- [ ] B7 加入：调用前 `estimate_cost(spec)` 与调用后写 `model_calls`
- [ ] B8 加入：水印/元数据写入（在 Provider 层）

#### 3.1.3 工作流引擎（`app/services/pipeline/`）
- [ ] B9 定义 Step 协议：`name, inputs, outputs, run(ctx), retry_policy, idempotency_key`
- [ ] B10 定义 Pipeline DAG：节点 + 显式依赖；存储到 `pipeline_runs` 与 `pipeline_steps`
- [ ] B11 调度器：基于 Celery，把 ready Step 派发到对应队列
- [ ] B12 状态机：`queued / running / partial_failed / awaiting_review / succeeded / failed / cancelled`
- [ ] B13 单步重跑接口：`POST /pipelines/:id/steps/:name/rerun`
- [ ] B14 审批接口：`POST /pipelines/:id/steps/:name/approve|reject`

#### 3.1.4 各 Agent Worker 骨架
- [ ] B15 ResearchAgent：抓热点 / 关键词扩散 / 候选选题（输入 Brief，输出 Topics）
- [ ] B16 ScriptAgent：按选题、模板、口吻生成脚本和镜头表草稿（输入 Topic，输出 Script + ShotList draft）
- [ ] B17 ArtAgent：生成角色卡 / 风格板 / 关键帧（输入 ShotList + Character，输出 reference assets + 关键帧）
- [ ] B18 VideoAgent：调用模型网关生成镜头片段（输入 Shot + 关键帧，输出 Render）
- [ ] B19 VoiceAgent：旁白 / 配乐 / 音效（输入 Script，输出 audio tracks）
- [ ] B20 EditAgent：FFmpeg 拼接、字幕烧录、比例适配（输入 Renders + Audio + Subtitles，输出 草稿成片）
- [ ] B21 ReviewAgent（v1 占位，仅做规则校验：时长、字幕、违禁词）
- [ ] B22 PublishAgent（v1 仅做导出，发布留 Phase 3）

#### 3.1.5 API 层（`app/routers/pipeline.py`）
- [ ] B23 `POST /briefs`、`GET /briefs/:id`
- [ ] B24 `POST /pipelines`（基于 Brief 启动）、`GET /pipelines/:id`
- [ ] B25 `GET /pipelines/:id/steps/:name/artifacts`
- [ ] B26 `POST /pipelines/:id/cancel`
- [ ] B27 SSE：`GET /pipelines/:id/stream`（关闭后可重连，状态从 DB 拉）

### 3.2 前端任务（Phase 1 内仅做最小可用版）
- [ ] F1 新建 `/app/project/[id]/pipeline` 页面：节点列表 + 状态 + 当前产物预览
- [ ] F2 节点详情抽屉：输入、输出、模型、成本、耗时、错误堆栈、单步重跑、审批
- [ ] F3 Brief 表单页：替代当前“快速生成”作为新入口（保留旧入口）
- [ ] F4 Pipeline 状态映射：把后端 6 种状态对应到 UI 视觉
- [ ] F5 失败回退提示：把 Toast/Banner/Retry 复用到 Pipeline 视图

### 3.3 验收
- 可以从 Brief 启动一条 Pipeline，跑出 30 秒成片，过程中至少有 1 次单步重跑成功，1 次人工审批通过。
- `model_calls` 表能查到每次外部调用的成本、模型、耗时。
- Pipeline 状态在浏览器关掉重开后能恢复。

---

## 4. Phase 2：质检、版本与成本拦截

### 4.1 后端
- [ ] B28 ReviewAgent v2：
  - 静态规则：时长、比例、字幕同步、违禁词
  - 启用模型：画面瑕疵粗检（OCR + 关键帧抽样）
  - 输出 `reviews.issues[]`，含 severity、artifact_ref、建议处置
- [ ] B29 版本系统：
  - 任何 Agent 输出都写一个 version（带 parent_id）
  - 提供 diff 接口：脚本/分镜/字幕的版本对比
  - 发布前一致性校验：脚本版本 == 字幕版本 == 配音版本 == 镜头版本
- [ ] B30 成本与配额：
  - `model_quotas` 支持 tenant 级 / project 级
  - Pipeline 启动前预估总成本（estimate_pipeline_cost）
  - 单步执行前预扣，失败后退还
  - 全局并发上限（按模型分桶）
  - 超额拦截 + 替代降级策略
- [ ] B31 任务退避与死信：
  - 队列分级：高优（用户交互）/ 默认（生成）/ 低优（批量）
  - 指数退避 + 抖动
  - 死信队列 + 人工捞回接口

### 4.2 前端
- [ ] F6 Review 面板：把 issues 渲染为可点击列表，定位到具体镜头/字幕/音轨
- [ ] F7 版本切换：每个产物显示版本号 + 可选回滚
- [ ] F8 成本面板：项目维度展示已花费、预估剩余、配额上限
- [ ] F9 启动前预估弹窗：列出每个 Agent 的预估成本

### 4.3 验收
- 任何镜头都能看到 v1、v2、v3 切换，发布前会强制校验版本一致性。
- 触发超额时会被拦截或降级到备选模型，不会静默烧钱。

---

## 5. Phase 3：发布、复盘、Metrics

### 5.1 后端
- [ ] B32 PublishAgent：
  - 输入：成片 + 多平台模板
  - 输出：每个目标平台的 PublishPlan（标题、封面、比例、标签、改写文案）
  - 真发布的对接（v1 至少 YouTube + Bilibili API；其余平台先做导出包）
- [ ] B33 Metrics 抓取：
  - 周期任务从 YouTube Data API、B 站开放 API 拉指标
  - 写入 `metrics`，按平台/视频/时间窗
- [ ] B34 复盘 Agent：
  - 基于 metrics 输出复盘草稿（哪条爆了，哪条扑街，可能原因）
  - 输出“下一轮流程规则”候选项，由人决定是否写回 Brief 模板

### 5.2 前端
- [ ] F10 PublishPlan 编辑器：每个平台独立 tab，预览不同比例
- [ ] F11 发布历史 + Metrics 面板（折线 + 关键 KPI）
- [ ] F12 复盘报告卡片：可一键“沉淀到 Brief 模板”

### 5.3 验收
- 一条成片能从 Pipeline 直接走到 YouTube / B 站发布并自动回收 24h 内指标。
- 至少能产出一份基于真实数据的复盘报告。

---

## 6. Phase 4：Pipeline 前端视图升级

### 6.1 前端
- [ ] F13 节点图视图（DAG）：基于 react-flow 或自研，展示节点依赖、状态、瓶颈
- [ ] F14 时间轴视图：横向展示每个 Agent 的耗时和并发占用
- [ ] F15 产物对比视图：左右对比版本（图、视频、字幕、音轨）
- [ ] F16 平台预览视图：同一成片在不同比例下的呈现（含 safe area 标尺）
- [ ] F17 审批中心：跨项目聚合所有 awaiting_review 节点

### 6.2 后端
- [ ] B35 优化 SSE/轮询合并接口，降低服务端推送压力

### 6.3 验收
- 一个有 30 个镜头的项目能在 DAG 视图里清楚看到瓶颈节点；单步重跑、版本切换、审批不依赖刷新页面。

---

## 7. Phase 5：合规、水印、滥用治理

### 7.1 后端
- [ ] B36 内容审核 Agent：
  - 触发点：脚本生成后、镜头生成后、发布前
  - 输出 risk score 与拦截/告警
- [ ] B37 水印系统：
  - 不可见水印（视频帧 + 音轨）
  - 可见水印（按订阅档决定）
- [ ] B38 使用日志 + 黑名单：
  - 声音克隆、数字人调用全程留痕
  - 高风险账号自动限制
- [ ] B39 Asset 来源追踪：
  - 上传时强制选择来源类型（自有 / 授权 / 公开素材 / AI 生成）
  - 衍生链 derivation_chain 自动维护

### 7.2 前端
- [ ] F18 上传时合规弹窗
- [ ] F19 风险面板（管理员）

### 7.3 验收
- 任何高风险调用都能在 24h 内被审计追溯到用户、项目、模型、时间。

---

## 8. Phase 6：批量化与多模型路由

### 8.1 后端
- [ ] B40 队列分级：交互 / 生成 / 批量 / 死信
- [ ] B41 模型路由策略：按租户、按内容类型、按价格、按可用性灰度
- [ ] B42 批量 Brief：模板化 Brief × 选题池 × 平台 = 大批量任务
- [ ] B43 矩阵号管理（多账号 + 平台凭证）

### 8.2 前端
- [ ] F20 批量任务面板（任务池 + 失败率 + 平均成本）
- [ ] F21 矩阵号管理页

---

## 9. 数据模型迁移路径（关键）

### 9.1 兼容策略
- v1 期间 `Project / Scene` 和新模型并存：
  - 旧入口 `/app/project/[id]` → 仍走 Scene-based 单段生成
  - 新入口 `/app/project/[id]/pipeline` → 走完整流水线
- 数据库不强制迁移老 scenes 到 shots，避免一次性大改。

### 9.2 后续合并
- Phase 4 末，把“快速生成”内部实现替换为“走 Pipeline 但只激活子集 Agent”；前端页面保留两种 UI。
- 老 scenes 表保留只读半年后再考虑清理。

---

## 10. 风险登记（强制每周回顾）

| 风险 | 触发条件 | 监测指标 | 兜底 |
|---|---|---|---|
| 成本爆炸 | 单项目日成本 > 阈值 | model_calls 日累计 | 自动降级 + 通知人工 |
| 任务雪崩 | 队列堆积 > 阈值 | Celery 队列长度、失败率 | 限流 + 死信 + 暂停接单 |
| 角色漂移 | 同一角色多镜头风格分数 < 阈值 | ReviewAgent 评分 | 强制回到关键帧重生 |
| 版权违规 | 上传含人脸/影视片段 | 内容审核 Agent | 拦截 + 通知 |
| 模型供应商 | 单家失败率 > 5% | provider 维度统计 | 自动切备选 |
| 数据断裂 | metrics 抓取失败连续 3 次 | publish_metrics_job | 告警 + 手动补抓 |

---

## 11. 团队与排期建议

- **后端 1 人专职**：负责数据模型、模型网关、工作流引擎、Agent worker。
- **前端 1 人专职**：负责 Pipeline 视图、Brief/Review/Metrics 面板。
- **算法/全栈 0.5 人**：负责 Agent 内部 Prompt 设计、模型调优、质检规则。
- **Phase 1 必须并行**：模型网关、工作流引擎、第一条 Demo Pipeline 三件齐头并进。
- **每个 Phase 留 20% Buffer 给 ADR 调整**。

---

## 12. 立即可以动手的事（本周可执行）

1. ✅ 决定工作流引擎策略 → `fliki-clone-api/docs/adr/001-workflow-engine.md`（自研轻量 runner）。
2. 🟡 设计 `briefs / shot_lists / shots / renders / model_calls / versions` 字段并落迁移：首期已完成 `model_calls` / `pipeline_runs` / `pipeline_steps`（迁移 `7f51c2a48e10` / `9a6e4d127b58`），其余表留下一批。
3. ✅ 起最小 `model_gateway`（`app/services/model_gateway/`）：types / cost / providers / gateway；首个 provider 是 OpenAI 兼容 LLM（指向 SiliconFlow）。
4. ✅ `/app/project/[id]/pipeline` 页面打通：用 polling 拉状态（SSE 留 Phase 2）。
5. ✅ 起 ResearchAgent + ScriptAgent + `script_only` 模板，能从 Brief → 选题 → 脚本 + 分镜草稿（强制 awaiting_review）。

---

## 13. Phase 1 起步进展（2026-05-04）

### 已完成（截至 2026-05-04 第二批迭代）
- ADR-001：工作流引擎选型（自研 Celery + 状态表轻量 runner）
- 数据模型：`model_calls`、`pipeline_runs`（含 `cost_reserved_usd`）、`pipeline_steps`、`model_quotas`（user 级月度额度 + 并发上限 + 当前周期使用）—— 已 `alembic upgrade head` 应用到本机 DB（最新 rev `c1e8d3b2f0a9`）
- `app/services/model_gateway`：
  - 统一类型（`ModelAction` / `ProviderName` / `RenderRequest` / `RenderResult` / `CallStatus`）+ 成本估算 + 同步 `record_call` 写 `model_calls`
  - `Gateway` 单例：`select_provider` 支持「同 ProviderName 下多 capability provider 并存」（修复了 LLM provider 被视频 provider 覆盖的 bug）
  - Provider：`OpenAICompatLLMProvider`（DeepSeek-V3 via SiliconFlow，支持 `response_format=json_array`，括号计数 + 围栏容忍的稳健解析）、`KlingProvider`（GENERATE_VIDEO + IMAGE_TO_VIDEO，含 negative_prompt）、`SiliconFlowVideoProvider`（Wan 系列）、`SiliconFlowTTSProvider`（`/audio/speech`，自动 fallback 到 `FunAudioLLM/CosyVoice2-0.5B`）、`SiliconFlowImageProvider`（`/images/generations`，按 aspect 自动推断 image_size，自动 fallback 到 `Kwai-Kolors/Kolors`）
- `app/services/pipeline`：Step 协议、注册表、Context、轻量 runner（`start_run` / `tick` / `execute_step` / `rerun_step`）
- 内置 Agent（7 个全部注册）：`ResearchAgent`、`ScriptAgent`、`ArtAgent`、`VoiceAgent`、`VideoAgent`、`EditAgent`、`ReviewAgent`
  - `ArtAgent`（v2）：1 次 LLM 出 enhanced_prompt + 风格板 + 角色卡（约 $0.002 / 24s）→ 默认为每镜调一次 GENERATE_IMAGE 出关键帧（Kolors 约 $0.005 / 4-7s/张），关键帧 URL 写入 `shots[i].keyframe_url`；可由 `brief.skip_keyframes=true` 关闭。单镜失败仅 warning，不阻断 step
  - `VoiceAgent`：一次性整段合成；按 shots.duration_s 累加生成字幕轨；缺失 / 失败时优雅降级（returns SUCCEEDED with warning，不阻塞下游）；上传到 R2 / 本地静态目录
  - `VideoAgent`：优先用 `art.shots[i].enhanced_prompt`，回退 `script.shots[i].visual`；prompt 里加上 art 的 negative_prompt 透传到 Kling。**`art.shots[i].keyframe_url` 存在时自动切到 `IMAGE_TO_VIDEO`** + ref_image，提升镜头一致性；缺关键帧的镜头自动回退 GENERATE_VIDEO，每镜独立决策
  - `EditAgent`（v3）：拼接 + 混音 + **字幕硬烧**一次性 ffmpeg 完成（`subtitles` 滤镜，强制重编码）；自动选择含 CJK glyph 的字体（macOS `Hiragino Sans GB`、Linux `Noto Sans CJK SC`）；不依赖 ffmpeg 的 `-shortest`（已知 mp3+libx264 组合下会丢音轨），改用 ffprobe 取两路时长 + `-t min_duration` 显式截短；同时输出独立 `.srt` 公开 URL 供下载；逐级降级（含字幕 → 仅混音 → 静默版）；产物含 `preview_url` / `silent_video_url` / `narration_url` / `subtitle_url` / `subtitles` / `muxed` / `burned_in_subtitles` / `warning`
  - `ReviewAgent`：v1 静态规则，新增对 art / voice / edit-muxed 的检查（mux 失败会以 warning 级 issue 暴露）
- 模板：`script_only`、`video_demo`、`video_full`（research → script → art → voice → video → edit → review）
- Celery 队列分级（`services/pipeline/celery_app.py` + `tasks.py`）：
  - 队列：`interactive`（research / script / review）、`media`（art / voice / video / edit）、`default`（tick 调度）
  - `pipeline.tick` task：单步调度，claim 一个 ready step → `apply_async(queue=queue_for_agent(agent_type))`；没 ready 时 settle run state
  - `pipeline.execute_step` task：worker 里执行 step，完成后链式 `tick_task.delay(run_id)` 触发下一轮
  - `task_acks_late=True` + `worker_prefetch_multiplier=1`：长任务挂掉不丢 ack
  - `_schedule_tick(run_id, bg)` dispatcher：`celery_enabled=true` → `tick_task.delay`，否则 → `BackgroundTasks.add_task(tick, run_id)`（dev / 没起 redis 时无缝回退）
  - 启动命令：`cd fliki-clone-api && make pipeline-worker`（Makefile 也提供 `pipeline-worker-media` / `pipeline-worker-interactive` 拆分模式）
- 配额闭环（user 级，月度，按月自动 rollover）：
  - `services/pipeline/cost.py::estimate_pipeline_cost(graph, brief)` 模拟 graph 执行上下文（mock shots / script / art / voice 上游 outputs）逐步调 `Step.estimate_cost_usd`，给出 `total_usd` + 每步明细
  - `services/pipeline/quota.py`：`get_or_create` / `reserve` / `release` / `count_active_runs`；`reserve` 走 `SELECT ... FOR UPDATE` 互斥；自动按自然月 rollover
  - `POST /pipelines` 启动前：估值 → 并发上限校验 → `reserve(total)` → start_run（落 `cost_reserved_usd`）；启动失败立即 `release(total)` 回滚
  - 终态时（`runner._settle_run_state` 首次进入 `succeeded`/`failed`/`cancelled`）累计 `cost_actual_usd` 并 `release(reserved - actual)` 退差额
  - `cancel` 单独走相同的 `release` 路径，避免被中断的 run 永久占额度
- API：`POST /pipelines`、`GET /pipelines/{id}`、`POST /pipelines/{id}/tick`、`/steps/{name}/rerun`、`/steps/{name}/approve`、`/cancel`、**`GET /pipelines/quota`**（剩余 / 上限 / 已用 / 周期开始 / 并发情况）、**`POST /pipelines/estimate`**（不启动只估值）
- 前端：
  - `src/lib/pipelines.ts` API 客户端 + 类型（含 `getPipelineQuota` / `estimatePipeline`）
  - `/app/project/[id]/pipeline` 编排页：Brief 输入、模板下拉（`script_only` / `video_demo` / `video_full`）、节点列表、单步重跑、审批、成本 & 配额面板（4 格 stat：本次预估 / 本次预扣 / 实际花费 / 本月剩余配额）+ 每步预估明细折叠 + 启动按钮的「本次成本嵌入 + 闸门 disable」（额度不足显示 "$X > 剩余 $Y"，并发上限显示 "X/Y 个 run 在跑"）
  - 各 agent_type 专属预览：
    - `art` → 风格板卡片（aspect/style/palette/lighting/camera）+ 角色卡列表 + 关键帧缩略图网格（每镜 1 张）+ 增强 prompt（含 ref-image ✓ 标记）折叠展开
    - `voice` → `<audio>` 直接播放旁白 + voice/model 元数据 + 字幕轨折叠
    - `edit` → `<video>` 拼接预览（含「字幕已烧录 ✓」/「已混音 ✓」/「未混音」状态徽标）+ `.srt` 下载链接 + 可选独立旁白音轨 + 字幕折叠
    - `review` → 按 severity 高亮 issues（error / warning / info）

### 本批冒烟结论（基于真实 SiliconFlow / Kling key）
- DeepSeek-V3 LLM：6 选题 / 4-8 分镜 / art 增强 ≈ $0.001-0.003/次，10-25s
- SiliconFlow CosyVoice2 TTS：~30 字旁白 ≈ $0.0017，3-4s，本地兜底输出 mp3 24kHz 单声道
- SiliconFlow Kolors GENERATE_IMAGE：576x1024 一张 ≈ $0.005，4-7s；ArtAgent v2 跑 3 镜全过总耗时 47s（LLM 24s + 3 image）
- 路由 bug 修复后，`script_only` 端到端 awaiting_review；写库与 model_calls 全对账（含 fish-speech / Flux schnell 的 FAILED→DEGRADED→SUCCEEDED 演进轨迹）
- EditAgent v3：12s 静默彩条视频 + 7.2s 旁白 + 3 条 SRT 字幕 → mux + 字幕硬烧（中文渲染清晰）→ 7.13s 成片 h264+aac 双轨对齐；端到端 ~4s（不含 TTS）/ ~10s（含 TTS）；额外输出 `.srt` 公开下载
- 配额闭环：`script_only` 预估 $0.006 → `reserve` 后 `current_period_usage_usd=0.006, active_runs=1` → `cancel` 触发 `release` 退 $0.006-$0=$0.006 → 回到 `0/$10, active_runs=0`；月度上限改 $0.001 后 `start video_full` 返回 HTTP 402 + `insufficient quota: need $4.8540, used $0.0000/$0.00`
- Celery dispatch：`celery_enabled=false`（默认）走 BackgroundTasks（向后兼容）；强制 `true` 后 `tick_task.apply_async(queue="default")` 成功把消息 push 到 redis `default` 队列（队列长度 +1），worker 端注册 `pipeline.tick` / `pipeline.execute_step` 两个 task、绑定 `interactive / media / default` 三个 exchange

### SSE 流式推送（2026-05-04 完成；替代前端 2.5s polling）
- 事件总线 `app/services/pipeline/events.py`：sync `publish(run_id, event_type, payload)`（runner / worker / 路由共用）+ async `subscribe(run_id)`（FastAPI SSE 端点用，idle 时 yield None 作 idle tick 避免 `wait_for(__anext__)` 取消 redis 请求带来的状态不确定）；用 redis pub/sub 频道 `pipeline:run:{run_id}`；redis 不可用 / publish 失败仅 warning，不阻断主流程
- `runner.py` 钩子：4 个 `_mark_step_*` 末尾 publish `step_state`；`_settle_run_state` 仅在 `prev_state != new_state` 时 publish `run_state`；`tick(run_id)` 入口 publish 一次（`queued→running`）；celery worker 模式同样走这些钩子，事件天然跨进程
- `pipelines.py` 新增 `GET /pipelines/{run_id}/events` SSE 端点：先 `_ensure_run_owner` → 立即发 `event: snapshot`（首屏对齐）→ 订阅 redis → 终态 (succeeded/failed/cancelled) 后服务端主动断开（200ms 缓冲让尾部事件流出）；25s 注释行 `: ping` 心跳防代理超时；30 分钟兜底关闭
- `cancel` / `approve` 路由直接 SQL 改 step / run state，没经过 runner，所以**单独广播一次** `run_state` + 受影响的 `step_state`（保持事件源单一）
- 前端 `src/hooks/use-pipeline-stream.ts`：浏览器原生 `EventSource` + `withCredentials: true`（cookie 同源鉴权）；snapshot → setRun 全量；step_state → patch run.steps（按 id upsert）；run_state → 合并顶层字段保留 steps；连续 2 次 onerror → fallback 到 2.5s polling；进入终态自动关
- 前端 `pipeline/page.tsx`：移除 `pollOnce` / `stopPolling` / `pollTimer`；`run` 一变化 hook 自动连/断；右上角加 `StreamModeBadge`（emerald「实时」/ amber「轮询」 dot）让用户能看出当前模式
- 烟测：`event: snapshot` → `event: step_state ×2` → `event: run_state(succeeded)` → 服务端关闭，事件顺序与时序正确；ping 心跳由 25s 阈值控制不会刷屏；401 拒绝匿名连接

### EditAgent v4（2026-05-04 完成；按旁白循环视频 + 多比例导出）
- `services/media/ffmpeg.py::mux_video_with_audio` 扩展三参数（向后兼容，缺省值 = v3 行为）：
  - `loop_video_to_audio: bool = True` — `audio_dur > video_dur + 0.05s` 时在 ffmpeg 命令前加 `-stream_loop -1`，配合 `-t audio_dur` 让视频无缝循环到旁白结束；`audio_dur <= video_dur` 时按 audio 截短（旁白讲完就停，观感更顺）
  - `target_aspect: Optional[str]` — `9:16` / `16:9` / `4:5` / `1:1` / `4:3`；新建 `ASPECT_TARGET_RES` 表把 aspect 映射到统一目标分辨率（`9:16→1080×1920`、`16:9→1920×1080`、`4:5→1080×1350`、`1:1→1080×1080`、`4:3→1440×1080`）；`setsar=1` 防止某些播放器按 DAR 二次拉伸
  - `aspect_fit: "cover" | "contain"` — `cover`（默认）等比放大后裁掉超出部分填满目标画幅；`contain` letterbox 黑边补齐
  - vf chain 顺序：`scale → crop/pad → subtitles`（字幕在 scale 之后烧，字号才不被缩放影响、跨比例视觉一致）
- `EditAgent` v4：在 v3 字段全保留的基础上新增多比例输出
  - 主比例解析优先级：`brief.primary_aspect` > `art.style_board.aspect_ratio` > `shot[0].aspect_ratio` > `16:9`
  - `brief.export_aspects` 控制额外输出：缺省仅出主比例；`["9:16","16:9","4:5"]` 触发多比例；字符串 `"all"`/`"common"` 走推荐三件套；主比例永远在第一位
  - `brief.aspect_fit` 控制 cover/contain，缺省 `cover`
  - 输出新增 `previews_by_aspect: { "9:16": {url, muxed, burned_in_subtitles, looped_video, aspect_fit, warning}, ... }`、`primary_aspect`、`aspect_fit`、`looped_video`；`preview_url` 仍指向主比例（前端不改也能跑）
  - 三级降级保持：含字幕烧录 > mux 无字幕 > 静默版；任一比例失败仅记 `warning`，不阻塞其他比例 / 整个 step
- 前端 `pipeline/page.tsx` 抽 `EditArtifact` 子组件 + `AspectTabs`：≥2 个比例时显示比例按钮组（默认选中主比例），切换时 `<video>` 重新加载；保留所有 v3 徽标，新增「视频已循环 ↻」徽标
- ffmpeg 烟测（4 场景全过）：循环模式 9:16 cover、禁循环 v3 行为、4:5 contain、无 target_aspect 仅循环；输出时长 / 分辨率全部断言通过

### Celery 死信队列（2026-05-04 完成；后端纯活，前端列表留下次）
- **新表 `dead_letter_tasks`**（alembic head 推进到 `e58c4a1d2b73`）：
  - `task_name` (`pipeline.tick` / `pipeline.execute_step` / `background.tick`) + `args_json` / `kwargs_json` + 关联 `run_id` / `step_id` / `user_id` + `error` / `traceback` + `attempt_count` + `status` (pending/retried/discarded) + `first_failed_at` / `last_failed_at` / `notes`
  - 复合索引 `ix_dlq_user_status_created` 支持「按 user 列 pending」最常见查询
- **service `app/services/pipeline/dlq.py`**：
  - `push(task_name, args, kwargs, error, traceback_str, run_id, step_id)` 同步入库；user_id 自动从 `pipeline_runs` 反推
  - **软去重**：相同 `(task_name, args_json::text)` 的 pending 行 → attempt_count++ 而非新建（便于「同一逻辑任务反复失败」聚合）
  - `mark(id, new_status, notes)` 标 retried / discarded
  - `list_for_user(user_id, status?, run_id?, limit)` / `get(id)` 查询
- **入库路径**：
  1. **Celery 模式**：新增 `DLQAwareTask` base class 重写 `on_failure` hook；`tick_task` / `execute_step_task` 绑这个 base；celery 保证 `on_failure` 只在 `max_retries` 用尽后调用，所以入库语义 = 真正不可恢复
  2. **BackgroundTasks 模式**：`runner.tick` 包一层 `_tick_inner` + try/except，未捕获异常入 DLQ 标 task_name=`background.tick`
  3. 业务级 step 失败（`StepResult.FAILED`）**不**进 DLQ —— 那是正常状态机的一部分
- **API `app/routers/dlq.py`**（前缀 `/api/dlq`）：
  - `GET /dlq?status=&run_id=&limit=` 列；按 `user_id` 过滤
  - `GET /dlq/{id}` 详情（含 traceback）
  - `POST /dlq/{id}/retry` 仅 pending 可重投；通过 `_retry_dispatch` 走 `_schedule_tick` 等价路径（celery / background 自动选）；标 retried + notes
  - `POST /dlq/{id}/discard` 仅 pending 可丢弃；可附 notes
  - 重试后失败会**新增一行**而非复用旧行（便于审计每次重投）
- **6 场景烟测全过**：push 入库 + 软去重 attempt++ + list 鉴权 + retry 标 retried 走 BackgroundTasks dispatcher + 已 retried 项再 retry 返 400 + discard 带 notes

### 前端切到 /api/production/* 新 API（2026-05-04 完成）
- 新增 `src/lib/production.ts`：types + 12 个 fetch helpers（getRunShotList / getRunRenders / getFileRenders / getRunReviews / getRunMetrics / listFile + create/patch/delete for publish-plans / versions / publishVersion）
- 新增 `src/hooks/use-run-renders.ts`：根据 runId + enabled 拉 `/production/runs/{id}/renders`；提供 `reload()` 触发器 + AbortController 清理；失败时不清空旧数据
- `EditArtifact` 改造：
  - 优先用 `useRunRenders(runId, { enabled: edit step in succeeded/awaiting_review })` 的数据（**权威源**，runner 顺序保证 persist 在 SSE publish 之前完成）
  - `outputs_json.previews_by_aspect` 仅在 API 还没返数据时作 fallback（兼容期 / 老 run）
  - 加数据源徽标：「renders 表」（emerald）/ 「outputs_json」（amber，提示兼容模式）
  - `aspectKeys` 变化时自动迁移 `selectedAspect` 到合理 tab，避免 stale state
- 新增 `ProductionPanel`（pipeline 页面下方）：
  - 「版本」列：列出 `listFileVersions`；当前 run 是 succeeded 时启用「另存为版本」按钮（label + notes + primary_render 下拉 + is_published 复选）；行里支持「置顶」（互斥替换 published）+ 删除
  - 「发布计划」列：列出 `listFilePublishPlans`；「新建发布计划」按钮（platform + render 下拉 + scheduled_at + title）；行里支持 status 下拉切换 + 标记 published 快捷按钮 + 删除
  - 「刷新」按钮 + delete 前 confirm
- 端到端 CRUD 烟测全过：
  - 创建 v1 (is_published=true) → 创建 v2 (is_published=true) → v1 自动 unpublish ✓
  - 创建发布计划带 tags = ["AI","video"] → JSON 保留正确 ✓
  - PATCH status: draft → scheduled ✓
  - DELETE 全部回收 `{deleted: true}` ✓

### 数据模型扩展 v1（2026-05-04 完成；7 张生产元数据表 + backfill + persist hook + router）
- **新表**（alembic head 推进到 `a4d72b91e3c5`）：
  - `shot_lists`     一个 run 一个分镜表（含 title / hook / script / cta / topic / style_board / character_cards / aspect）
  - `shots`          每个 shot 一行（按 `(run_id, index)` 自然键 upsert；script→art→video 三次 persist 合并到同行）
  - `renders`        EditAgent v4 每个 aspect 一行（`(run_id, aspect)` 主比例唯一约束 = partial unique index where is_primary=true）
  - `reviews`        ReviewAgent 每条 issue 一行（severity / area / message / meta_json）
  - `publish_plans`  发布计划（platform / status / scheduled_at / external_id / tags / cover）
  - `metrics`        指标时间序列（kind / value_num / value_text / unit / captured_at）
  - `versions`       run 快照标签（label / primary_render_id / is_published 互斥）
- **数据迁移**：alembic 内 `_backfill_from_outputs_json` 解析所有现有 pipeline_runs 的 step outputs_json 写入新表；幂等（按 run_id 先 DELETE 再 INSERT）；初次跑出 1 shot_list + 8 shots（历史只跑过 script_only）
- **persist 切入点**：`app/services/pipeline/persist.py::persist_step_outputs(run_id, step_id, agent_type, outputs)` 同步函数，按 agent_type 路由到 6 个 handler（script/art/video/voice/edit/review）；在 runner 的 `_mark_step_succeeded` / `_mark_step_awaiting_review` 之后调用；任何异常仅 logger.exception 不阻断 step 状态机
- **handler 责任**：
  - script → 创建 shot_list（如不存在）+ upsert shots 的 narration/visual/camera/duration
  - art → 更新 shot_list 的 style_board/character_cards/aspect + upsert shots 的 art 字段
  - video → upsert shots 的 video_url / provider / model / mode / cost / duration_ms / model_call_id / error
  - voice → 写 `voice_char_count` / `voice_subtitles_duration_s` 两条 metric（subtitles 仍在 outputs_json）
  - edit → 删旧 renders + 按 previews_by_aspect 重建（v4）；v3 fallback 用顶层 preview_url 单行
  - review → 删旧 reviews + 按 issues 重建（按 step_id 局部清理，单步重跑安全）
- **新路由 `routers/production.py`**：
  - `GET  /production/runs/{id}/shot-list` → ShotListOut + 嵌套 shots
  - `GET  /production/runs/{id}/renders`    / `GET /production/files/{id}/renders` → list[RenderOut]
  - `GET  /production/runs/{id}/reviews`    → list[ReviewOut]（按 severity 排序）
  - `GET  /production/runs/{id}/metrics?kind=` → list[MetricOut]
  - `GET  /production/files/{id}/publish-plans` / `POST /production/publish-plans` / `PATCH /production/publish-plans/{id}` / `DELETE /production/publish-plans/{id}`
  - `GET  /production/files/{id}/versions` / `POST /production/versions` / `POST /production/versions/{id}/publish`（互斥置 is_published）/ `DELETE /production/versions/{id}`
- **outputs_json 状态**：保留**不动**，作为 SSE snapshot 给前端的"快照视图"；前端无需立刻改读新 API（兼容期），前端切换将作为下一轮工作
- **烟测**：构造 fake run 串行 persist 5 agent，shot_list / shots（按 index 合并）/ renders（3 aspect 含主比例 + warning）全部数据正确；reviews / metrics 在 fake step_id 下触发 FK violation，证明 try/except 容错按预期工作

### ADR-002（2026-05-04 完成；agent orchestration 框架取舍）
- `docs/adr/002-agent-orchestration.md` 落地；明确**不引入 LangChain / LangGraph / CrewAI** 作为编排层
- 核心论点：我们的「Agent」是「生产线工位」（强契约 + 配额账本 + 审批 + provider 故障切换），与社区 LLM Agent（自主 reasoning + 自由对话）是两件事
- 留口子：单 Agent 内部可用 LangChain / LangGraph 做 LLM client / 多轮 tool 调用，只要 `Step.run(ctx) -> StepResult` 协议不变；但 provider 接入仍走 `model_gateway`（禁止绕过 record_call 计价）
- 写明 4 条触发条件，命中任一即开 ADR-003 重新评估（模板数 > 20 + 子 DAG 复用 / 真正动态 DAG / 跨 run 协调 / 团队 > 6 人）
- 写明 4 条「不做什么」避免漂移：不做 LLM 决定下一步 step、不做 Agent 自由对话（统一走 outputs_json）、不预编码框架抽象、不偷连 OpenAI 绕过 gateway

### 还没完成（按优先级）
1. VoiceAgent v2 字幕对齐：按 TTS 实际时长（whisper 反推 / word-level timestamps）重切字幕；v4 字幕仍按 shots.duration_s 均分，循环过的视频里字幕会跟旁白对不上
2. DLQ 前端列表：在 ProductionPanel 旁加一个「死信」tab 读 `/api/dlq?status=pending`；行内 retry / discard 按钮；当前后端可用，纯 curl 操作不便
3. 发布执行器：当前 publish_plans 只是元数据表 + 状态切换，没有真把 render 推到 bilibili / youtube 的 adapter；前端「标记为已发布」只改 status 不真发
4. EditAgent v5 字幕重排：按目标 aspect 调字幕字号 / 位置；当前 v4 各 aspect 共用同一份 force_style
5. ArtAgent v3：角色一致性闭环（identity 锁定 + IPAdapter / Flux Redux / 角色 LoRA）；目前 v2 是按镜独立出图，跨镜角色形象会漂
6. shots 数据用起来：数据已经在表里，但前端 art / video step 卡片仍读 outputs_json；切到 `/production/runs/{id}/shot-list` 能看到合并视图（含 art prompt + video URL 同行）
7. 前端 Pipeline 节点图视图（react-flow）+ 版本切换 + 平台预览
8. 配额 v2：tenant 级支持、provider 级并发分桶、按 plan 自动设额度、月底自动通知

### 立即可以验证
1. 迁移已 `upgrade head`；后端运行（**注意 cwd 必须是 fliki-clone-api**，否则 pydantic-settings 读不到 .env）：
   ```bash
   cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
   .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   想跑 Celery worker 模式，先在 `.env` 把 `CELERY_ENABLED=true`，再起一个 worker：
   ```bash
   cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && make pipeline-worker
   ```
2. 启动前端：`cd fliki-clone && npm run dev`
3. 登录后访问 `/app/project/<任意id>/pipeline`：
   - `script_only`：research → script(awaiting_review) → 通过 → succeeded
   - `video_demo`：research → script → video(每镜 1-2 min) → edit → review
   - `video_full`：在 demo 基础上多两个并行 step（art + voice），video step 用增强 prompt
4. `video_full` 完成后：
   - `edit` step 卡片下：拼接成片 + 独立旁白音轨 + 字幕条
   - `art` step 卡片下：style_board + 角色卡 + 增强 prompt 列表
   - `voice` step 卡片下：可直接播放的 `<audio>`
5. `SELECT provider, action, model, status, cost_usd, duration_ms FROM model_calls ORDER BY created_at DESC LIMIT 20` 能看到 LLM / Kling / TTS 每条调用的明细（fallback 时 status=`degraded`）

### 已知限制（写明，避免被反复发现）
- 调度器双模式：`celery_enabled=false`（默认）时仍是 BackgroundTask 同进程顺序执行，视频步骤会占用一个 worker 进程数分钟；`celery_enabled=true` + `make pipeline-worker` 起独立 worker 后 step 异步消费，FastAPI 请求线程立即返回。
- `EditAgent` v4 已支持：混音 + 字幕硬烧（中文走 Hiragino Sans GB / Noto Sans CJK SC）+ SRT 文件输出 + 按旁白时长循环视频 + 按 `style_board.aspect_ratio` 多比例导出（cover/contain）。仍不做：按音频实际时长重新切字幕（字幕节拍仍按 shots.duration_s 均分），多个 aspect 都用同一份字幕（不重排版面到对应画幅）。
- `ReviewAgent` 只做静态规则；瑕疵 / 字幕同步 / 口型偏差等需要 LLM + 视觉模型，留 Phase 2。
- `ArtAgent` v2 出每镜独立关键帧；同一角色跨镜的「形象一致性」未在 prompt 层强约束，会有漂移；强一致性留 v3（IPAdapter / 角色 LoRA / Flux Redux 风格嵌入）。
- `VoiceAgent` 不做强对齐：TTS 实际时长可能 ≠ shots.duration_s 之和；EditAgent v3 用 ffprobe 取两路实际时长 + `-t min_duration` 截短，绕过了 ffmpeg 6.0 mp3+libx264 组合下 `-shortest` 丢音轨的 bug；但仍是「截短」语义，超长一方的尾部内容被丢；Phase 2 起改为按音频实际时长重新切字幕 + 视频拉伸/补黑场。
- SiliconFlow 不时下线模型（实测：fish-speech、FLUX.1-schnell 都已禁用）；`.env` 已切到 `FunAudioLLM/CosyVoice2-0.5B` / `Kwai-Kolors/Kolors`；两个 provider 仍保留自动 fallback 兜底。
- 取消 (`/cancel`) 不会强切断已经在跑的视频生成调用，只阻止后续 step；但会立刻退还预扣额度。
- 成本预估 / 预扣 / 退还闭环已落地（user 级月度），但**估值精度依赖各 agent 的 `estimate_cost_usd`**——视频步骤按「典型 6 镜 × 4s × $0.20/s」算，真实 shots 数 / 时长 / provider 偏差时实际花费可能偏高/低；启动后实际花销以 `model_calls` 为准。
- 配额仅按 user_id 计；tenant / 团队级共用配额、按 plan 动态调额度、provider 级并发桶 → 留 Phase 2/3。
- ffmpeg 二进制必须在系统 PATH 内；缺失时 EditAgent 会降级到只输出拼接视频（无音轨）。

