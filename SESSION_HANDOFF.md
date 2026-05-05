# 跨会话交接（2026-05-04 全天 → 2026-05-05 全天：配额 v2 / VoiceAgent v4 / ArtAgent v3 / 发布执行器 v1 → 多 Agent 并行第一波 7 Track + 第二波 4 Track 全合）

> 这一份是"贴到下个会话开头就能无缝接力"的最小集；详细技术点在 `DEVELOPMENT_PLAN.md` 第 13 节。
> 关键约束 / 已知坑请认真读完再写代码。

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

- **后端 pid 30876**（仍在 11:13 启的进程；监听 `127.0.0.1:8000`，无 proxy 污染；
  代码改了未重启 → **下次重启就会加载第二波 4 Track 新代码 + alembic head `a1b2c3d4e5f6`**；
  已落库的能力：配额 v2 / VoiceAgent v4 / ArtAgent v3+v4 IP-Adapter / 发布执行器 v1
  含 confirm_real_publish 列 / faster-whisper 本地 fallback / Fernet 凭证加密）
- **前端 pid 8947**（next dev，3000 端口，hot-reload 改动无需重启；
  第二波 4 Track 的前端改动会自动 hot-reload）

**第二波合并后必做**：

```bash
# 1. 停旧 backend（pid 30876）
kill 30876

# 2. 跑 alembic（如果你跨过 12:35 没启过新 backend，就把 feature_flags 迁移落库）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m alembic upgrade head   # → a1b2c3d4e5f6

# 3. 启新 backend（不带 --reload）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. 验证（应看到 119 routes / 6 billing / 4 admin-flag / SSE publish-events）
.venv/bin/python -c "from app.main import app; print(len(app.routes))"
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

| 优先级 | 任务 | 工作量 | 触发条件 / 价值 |
|---|---|---|---|
| ~~★★★~~ ✅ | ~~VoiceAgent v2/v3/v4 字幕对齐 + word-level~~ | ~~2 天~~ | **2026-05-04 22:00 / 22:30 / 05-05 10:00 完成** |
| ~~★★~~ ✅ | ~~DLQ 前端列表~~ | ~~半天~~ | **2026-05-04 21:00 完成** |
| ~~★★~~ ✅ | ~~发布执行器 v1 + Track-01 凭证 Fernet 加密 + Track-02 confirm_real_publish 列~~ | ~~2 天~~ | **2026-05-05 11:30 完成** |
| ~~★~~ ✅ | ~~ArtAgent v3 + v4 IP-Adapter 接入点 + Track-09 多角色锁定~~ | ~~2 天~~ | **2026-05-05 10:45 + 13:55 完成** |
| ~~★~~ ✅ | ~~配额 v2 tenant 级分桶~~ | ~~半天~~ | **2026-05-05 09:30 完成** |
| ~~★★~~ ✅ | ~~publish 任务异步化（celery + SSE）~~ | ~~半天~~ | **2026-05-05 13:55 完成（Track-03）**：202 + dispatcher + SSE phase 流；BackgroundTasks fallback 共用 task body |
| ~~★★~~ ✅ | ~~canary / feature_flags v1~~ | ~~1.5 天~~ | **2026-05-05 13:55 完成（Track-10）**：alembic `a1b2c3d4e5f6`；ArtAgent 入口闸门 + admin 路由 |
| ~~★★~~ ✅ | ~~Stripe 计费 v2~~ | ~~2 天~~ | **2026-05-05 13:55 完成（Track-11）**：6 路由 + webhook 4 事件矩阵 + tenant_quotas/provider buckets bump |
| ★★ | **YouTube 真发 chunked PUT + 真账号 e2e** | 半天 | 当前 youtube adapter 用 resumable upload 一把发；1080p 大文件可能超 timeout；改 chunked 8-16MiB PUT，加进度回写 `plan.meta_json.upload_progress`；同时跑一次真 OAuth + 真上传 + 真 video_id 落 `external_id` 闭环 |
| ★ | **前端 Admin · Feature Flags 管理面板** | 1 天 | Track-10 当前只暴露 HTTP API；前端在 settings 加一个 tab：列 tenant 全部 flag + 滑块改 pct + Apply；带 audit log 展示（who / when / from / to） |
| ★ | **DLQ retry 识别 publish.execute_plan** | 1-2 小时 | Track-03 follow-up：当前 DLQ retry 走 `_retry_dispatch(tick_task)`，对 publish task 不生效；在 `routers/dlq.py::retry` 识别 `task_name="publish.execute_plan"` 时改派 `execute_publish_plan_task.delay(*args)` |
| ★ | **Stripe webhook handler 单元测试 + 失败支付路径** | 半天 | Track-11 follow-up：模拟 stripe Event payload 跑 `handle_webhook_event` 断言 DB 变化；补 `charge.refunded` 处理（v1 故意没接） |
| ★★ | **bilibili 自动发布**（依赖商务）| 2-3 天 | Track-12：等 MCN/合作伙伴入驻拿 OpenAPI；adapter stub 已留好 |
| ★ | **SSE 断网重连续传** | 半天 | 当前 `: ping` + onerror fallback 已够用；加 `last_event_id` 让客户端断网重连不丢事件（pipeline + publish 两条 SSE 一起做） |
| ★ | **ArtAgent v4 多角色 IP-Adapter 真接入** | 1-1.5 天 | Track-09 已把 anchors_by_role 喂进 `_generate_keyframes(image_url=)`；等 SiliconFlow Kolors-IP / Flux Redux 上 multi-IP 端点后，改 `siliconflow_image.py` 兼容多 ref，agents 不动 |
| ★ | **L-04 月账单 PDF + 邮件** | 1 天 | Track-11 follow-up：拿 stripe `invoice.paid` 渲染 PDF + 邮件 |
| ★ | **L-05 RBAC：workspace member editor/viewer 权限** | 1.5 天 | Track-10 admin 路由当前是邮箱白名单，正经 RBAC 还没做 |
| ★ | **L-11 model_calls 加 tenant_id + 按 tenant 聚合** | 半天 | 配额 v2 落地后，`model_calls` 表还在按 user 聚合；改成 tenant 维度成本看板 |
| ★ | **L-12 前端 i18n 完整覆盖** | 1.5 天 | 当前 zh/en 部分页面有缺失 |

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
│   └── 20260505_1300_add_feature_flags.py (rev a1b2c3d4e5f6)  ← head ★ Track-10
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
当前能跑 video_full 端到端：配额 v2 tenant + provider 桶 / VoiceAgent v4 word-level
（OpenAI Whisper 或本地 faster-whisper）/ ArtAgent v3+v4+v5（多角色 anchor 锁定，按
shot.focus_character 逐镜选 + canary 灰度按 tenant_id hash 染色 v4↔v3-prompt-only）/
VideoAgent v2 i2v 多角色 anchor / EditAgent v5 / 发布执行器 v1（dry-run/youtube/bilibili，
含 confirm_real_publish 列 + Fernet 凭证加密 + OAuth）+ publish 任务异步化（celery + SSE
phase 流）/ feature_flags v1 + admin 路由 / Stripe 计费 v2（webhook 落 tenant_quotas +
provider bucket bump）/ DAG 视图 / pytest 41 case 全过。
请直接做（除非我另说）：
(A) YouTube 真发 chunked PUT + 真账号 e2e（半天）；
(B) 前端 Admin · Feature Flags 管理面板（1 天）；
(C) DLQ retry 识别 publish.execute_plan task（1-2 小时）；
(D) Stripe webhook handler 单元测试 + charge.refunded（半天）；
(E) bilibili 自动发布（等 MCN，2-3 天，商务问题）。
开始前确认：(1) backend cwd 是 fliki-clone-api；(2) alembic head 是 a1b2c3d4e5f6；
            (3) 启动后端不带 --reload；(4) `cd fliki-clone-api && make test` 应 41 PASS；
            (5) 重启 backend 才会加载第二波 4 Track 新代码；
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
