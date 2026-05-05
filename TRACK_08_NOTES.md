# Track-08 · pytest 工程化 完成记录（2026-05-05）

> 分支：`track-08-pytest-suite`
> 范围：把过去几次会话的 ad-hoc smoke（已删）+ 当前模块全部转成 pytest test suite，CI ready。
> 严格遵守 AGENTS_BACKLOG.md：**不碰 `app/` 业务代码**，仅在测试目录 + Makefile + requirements-dev.txt 内工作。

## 1. 落地清单

| 文件 | 类型 | 作用 |
|---|---|---|
| `fliki-clone-api/tests/__init__.py` | 新增 | 模块声明 + 套件布局说明 |
| `fliki-clone-api/tests/conftest.py` | 新增 | 共享 fixture：`pg_engine` / `temp_tenant` / `temp_user` / `temp_file` / `temp_run` / `temp_render` / `fake_gateway` / `patch_gateway` / `make_ctx` |
| `fliki-clone-api/tests/test_quota_v2.py` | 新增 | 配额 v2 = 8 case（plan_defaults / resolve_anon / tenant_quotas CRUD / release floor / provider 桶 cycle / **20 线程并发竞态** / gateway rate_limited / gateway user_id fallback） |
| `fliki-clone-api/tests/test_voice_v4.py` | 新增 | VoiceAgent v4 = 7 case（标点切行 / 短碎片合并 / v1 fallback / v3 比例重切 / v4 word 强对齐 / v4 健康降级 / agent.run 端到端 mock gateway） |
| `fliki-clone-api/tests/test_art_v3.py` | 新增 | ArtAgent v3 = 8 case（mode resolve off / mode resolve no-cards / 主角选择 / anchor prompt 拼接 / inject 跳过非主角 / agent.run anchor 成功 / agent.run anchor 失败降级 / agent.run off mode） |
| `fliki-clone-api/tests/test_publishing.py` | 新增 | 发布执行器 = 8 case（dry-run unit / bilibili stub / youtube no-cred / unknown→dry-run fallback / executor 端到端 dry-run / 重复执行拒绝 / unknown 平台 fallback / youtube no-cred 写 failed） |
| `fliki-clone-api/pytest.ini` | 新增 | `tests/` 路径 + asyncio strict + marker（unit / integration / publishing / quota / voice / art / slow） + 默认 `addopts = -ra --strict-markers --tb=short` + 抑制 pydantic / SQLAlchemy DeprecationWarning |
| `fliki-clone-api/requirements-dev.txt` | 新增 | `-r requirements.txt` + `pytest>=8.3,<10` + `pytest-asyncio>=0.23,<2` + `httpx>=0.27` |
| `fliki-clone-api/Makefile` | 改 | 加 `install-dev` + `test-unit` + `test-integration` target；`test` 沿用 `pytest tests/ -v` |

## 2. 总数 / 分组

| 分组 | 数量 | 说明 |
|---|---|---|
| 总用例 | **31 PASS** | `make test` 全部绿 |
| `@pytest.mark.unit` | 21 | 完全 in-memory；无 PG / 无 ffmpeg / 无外网 |
| `@pytest.mark.integration` | 10 | 需要本地 PG（默认 `postgresql://zhaoguangyuan@localhost:5432/fliki`） |
| `quota` 标 | 8 | `test_quota_v2.py` 全部 |
| `voice` 标 | 7 | `test_voice_v4.py` 全部 |
| `art` 标 | 8 | `test_art_v3.py` 全部 |
| `publishing` 标 | 8 | `test_publishing.py` 全部 |

> 注意：用例总数 31 = 8 (quota) + 7 (voice) + 8 (art) + 8 (publishing)；art 比卡片要求多 0、voice 多 1（v4 健康降级单抽）、publishing 多 4（4 unit adapter + 4 integration executor）、quota 比卡片要求 6+ 多 2（plan_defaults + anon resolver 单元抽）。

## 3. CI ready

```bash
# CI 默认推荐（无 PG 也能跑）：
cd fliki-clone-api && make install-dev && make test-unit
# 21 PASS / 10 deselected

# 带 PG 的本地 / staging runner：
cd fliki-clone-api && make test
# 31 PASS

# 仅集成（diagnose PG / 索引 / 行锁问题时用）：
cd fliki-clone-api && make test-integration
# 10 PASS / 21 deselected
```

CI 推荐策略：
- PR 必跑 `make test-unit`（< 0.5s，零依赖）
- 主分支跑 `make test`（含 PG；本仓库 0.6s）
- 集成 case 自带 PG 不可达自动 `pytest.skip`，红线只在「PG 在但功能挂」时触发

## 4. 覆盖矩阵

### ✅ 已覆盖

| 模块 | 覆盖维度 |
|---|---|
| `app.services.pipeline.quota`（v2） | get_or_create_tenant / reserve_tenant 边界（usage+amount=limit ε 内允许）/ release 不会负 / count_active_runs_tenant 路径（间接通过 reserve cycle）|
| `app.services.pipeline.tenant` | resolve_tenant_id（anon / cache / user）/ resolve_tenant_context 匿名分支 / plan_defaults 4 plan + 未知 plan 兜底 |
| `app.services.pipeline.provider_buckets` | ensure_bucket plan-bump + 不缩小 / acquire 单线程 / acquire 20 线程并发严格 2 槽 / release GREATEST(0) / list_buckets / `BucketFull` 抛出 |
| `app.services.model_gateway.gateway.Gateway.run` | 桶满返 RATE_LIMITED 不计费 / user_id fallback 自动 resolve tenant + ensure 桶 + release 归 0 / record_call 路径（间接） |
| `app.services.pipeline.agents.voice` | `_split_narration_into_lines` 主分隔符 + 短碎片合并 + 硬切兜底 / `_build_subtitles_v1` 累加 / `_rescale_subtitles_v3` 字符比例 / `_build_subtitles_v4_word_aligned` 边界规整 + 单调性 + words 字段 / 健康降级（words 太少 / asr-origin ratio 失调）/ `VoiceAgent.run()` 端到端 v4 路径 |
| `app.services.pipeline.agents.art` | `_resolve_consistency_mode` off + no-cards 兜底 + 不合法值兜底 / `_select_protagonist` 显式命中 + cards[0] fallback / `_build_anchor_prompt` 含必要片段 + 长度限制 + wardrobe 缺失 / `_inject_consistency_into_shots` 主角注入 + 非主角跳过 + 重跑不重复 / `ArtAgent.run()` 三模式（auto+anchor 成功 / anchor 失败降级 / off） |
| `app.services.publishing.adapters` | DryRunAdapter mock external_id + `dryrun-` 前缀 / BilibiliAdapter stub 错误文案 / YouTubeAdapter 缺 token + 缺 client_id 两条失败路径 / `get_adapter` 未知平台兜底 dry-run |
| `app.services.publishing.executor` | 端到端 dry-run（plan→executor→DB published 落库 + external_id 回写）/ 重复 execute 已 published 拒绝 / unknown 平台兜底 dry-run / youtube 无凭证写 plan.error 不抛 |

### ⚠️ 暂未覆盖（NOTES，由协调者决定后续是否补）

1. **VoiceAgent ASR 失败降级路径**：当 ASR `result.ok=False` 时退到 v1，目前未单独 case；混进现有 v3/v1 fallback 行为里。
2. **VoiceAgent ffprobe 兜底路径**：`alignment_source='ffprobe'` 分支需要 ffmpeg + 真 mp3 bytes，留 follow-up；当前测试用 mock ASR 返 `duration_s` 直接走 `asr` 分支。
3. **ArtAgent LLM 解析失败 / shots 缺失**：`_parse_json_object` 容忍逻辑没单独 case（已被 `ArtAgent.run` 集成测试间接覆盖快路径）。
4. **publishing.oauth.py（OAuth start / callback）**：未覆盖；建议 Track-02（YouTube 真发安全闸门）合入后再加 cookie/state nonce case。
5. **publishing executor DLQ 路径**：当前 case 只验业务级 `ok=False`；adapter 抛 `PublishError` → DLQ 入库的链路没单独测，需要 mock celery 任务上下文，留待死信队列专项 follow-up。
6. **publishing youtube 真发路径**：依赖 `requests.post` 网络；当前测试用 monkeypatch 加 `confirm_real_publish=False` 走安全闸门覆盖了「假发返 mock id」分支，但真 200/4xx/5xx HTTP 路径需要 `responses` 或 httpx 拦截库。
7. **runner 配额闭环**：`runner.start_run` / `_settle_run_state` 没集成测；建议下次（Track-09 / Track-11）真起一个 `script_only` run 端到端测时一并加。
8. **pipeline / front-end SSE**：完全未覆盖（前端 cypress / playwright 体系另起）。

## 5. 发现并标注的潜在 issue（**不修**，由协调者决定）

> 互斥锁规定 Track-08 不动 `app/`；以下都是写 case 时观察到、可能值得跟进的事项。

1. **`.env` 多了 `PUBLISH_CREDENTIAL_FERNET_KEY` 但 `app/config.py` 没声明字段**
   - 来源：Track-01 (credentials Fernet) work-in-progress 的 .env 改动已落库，但 Settings 类没 merge
   - 影响：`pydantic_settings` 默认 extra='forbid'，`from app.config import get_settings` 直接抛 ValidationError，所有 import 链走 config 的代码（包括 alembic、celery worker、pytest）都会挂
   - 我的 workaround：`tests/conftest.py` 顶层动态包一层 Settings 子类，强制 `extra='ignore'`，仅影响测试进程；正式后端启动行为不变
   - **建议**：Track-01 合入时把 `publish_credential_fernet_key: str = ""` 字段加进 `app/config.py`，本 workaround 可以删但保留也无害
2. **`app.services.model_gateway.cost` 引用了 `ProviderName.FASTER_WHISPER_LOCAL`**
   - 来源：Track-06 (faster-whisper local) work-in-progress；当前在工作树但未提交
   - 我的 workaround：测试不引用该 enum，按 main HEAD 写
   - **建议**：合并顺序：Track-06 先 → Track-08 拿 main 后再合
3. **`VoiceAgent.run()` outputs 没把 `asr_words_count` / `subtitle_alignment_quality` 暴露**
   - 这两个字段在 `_align_subtitles` 内部 `info` dict 已经算出来了，但 outputs 没赋值
   - 影响：前端 `VoiceArtifact` 想展示「N words」徽标 + 对齐档位的话拿不到
   - 我的 workaround：测试只断言实际 outputs 字段
   - **建议**：协调者按需把 outputs 加 2 行字段映射，不影响其它 agent
4. **`provider_buckets.ensure_bucket` 自动 bump 行为可能与 SRE 期望冲突**
   - 现状：`max_override is None or desired_max > current_max` → 自动放大；缩小不动
   - 边界：只要某个 caller 临时按 enterprise plan 调一次，桶 max 会被永久提升到 30；之后免费 plan 再调过来也维持 30
   - **建议**：考虑加 `auto_bump=True` 默认参数让 SRE 显式关闭（不影响当前测试）

## 6. 烟测（自验证）

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api

# 1) 装依赖（pytest 等）
make install-dev

# 2) 全套（含集成）
make test
# === 31 passed in 0.74s ===

# 3) 仅单元
make test-unit
# === 21 passed, 10 deselected in 0.10s ===

# 4) 仅集成
make test-integration
# === 10 passed, 21 deselected in 0.53s ===
```

## 7. follow-up（建议下一波 Track）

- **Track 后续**：Track-04 / Track-09 / Track-10 落地后，本套件会被 break 的位置已标注 marker `# Track-XX 合入后扩 N case`；合入时跑 `make test-unit` 5s 内验证回归
- **CI 接入**：建议在 GitHub Actions 加一个 job：`pip install -r requirements-dev.txt && make test-unit`；PG 集成走专用 service container（postgres:17）
- **覆盖率统计**：`make test-cov` 已在 Makefile 里（pytest --cov）；初版按 module 覆盖率约 40%，下次配 `coverage>=` 阈值门禁

## 8. 提交信息

```
test: 引入 pytest 工程化；覆盖 quota v2 / VoiceAgent v4 / ArtAgent v3 / publishing
```
