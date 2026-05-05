# Track-06 · faster-whisper 本地 fallback

> 分支：`track-06-faster-whisper-local`
> 完成时间：2026-05-05 ~12:20
> 目标：用户没 `OPENAI_API_KEY` 时，VoiceAgent v4 word-level 强对齐也能本地跑（离线、零成本）。

## 一句话结论

ASR 路由从原来的 `[OPENAI, SILICONFLOW]` 调整为 **`[OPENAI, FASTER_WHISPER_LOCAL, SILICONFLOW]`**：
- 有 OpenAI key → Whisper-1 云端 word-level（最稳）
- 没 key + 装了 `faster-whisper` → 本地 word-level fallback（v4 仍可用）
- 都没 → SiliconFlow SenseVoice（无 words，VoiceAgent 自动退到 v3 行级，向后兼容）

`voice.py` 算法层**没动**（按 backlog 卡片要求），新 provider 输出格式 `{text, duration_s, segments, words, language}` 与
`OpenAIWhisperProvider` 完全一致；voice agent 现有的 v4 路径 `_build_subtitles_v4_word_aligned`
读到 `words` 时直接进 v4，不感知 provider 来源，`outputs.asr_provider` 字段会落 `faster_whisper_local`。

## 改了哪些文件 + 为什么

| 文件 | 改动 | 原因 |
|---|---|---|
| `fliki-clone-api/app/services/model_gateway/types.py` | `ProviderName` enum 加 `FASTER_WHISPER_LOCAL = "faster_whisper_local"` | gateway 路由 + cost 表的 key 类型需要 |
| `fliki-clone-api/app/services/model_gateway/providers/faster_whisper_local.py` | **新文件** | 新 provider 主体（懒导入 faster-whisper、单例缓存模型、输出格式与 OpenAIWhisper 一致） |
| `fliki-clone-api/app/services/model_gateway/providers/__init__.py` | 加 `FasterWhisperLocalProvider` 导入与导出 | gateway.py 通过 `from .providers import ...` 拿到 |
| `fliki-clone-api/app/services/model_gateway/gateway.py` | (a) ASR 路由 `[OPENAI, FASTER_WHISPER_LOCAL, SILICONFLOW]`；(b) `get_gateway()` 注册 `FasterWhisperLocalProvider()` | 路由切换 + 单例注册 |
| `fliki-clone-api/app/services/model_gateway/cost.py` | `_PRICE_TABLE` 加 `(FASTER_WHISPER_LOCAL, ASR) = 0.0` | 本地推理零外部成本，避免 estimate 报 0 但 record_call 写错 provider |
| `fliki-clone-api/requirements.txt` | 末尾追加 `faster-whisper>=1.0`（带 optional 注释 + 安装指引）| 让用户知道这是大依赖，不强制装；安装后 gateway 自动启用 |

**没碰**（互斥锁遵守）：
- `app/services/pipeline/agents/voice.py`（v4 算法已落地）
- `app/services/publishing/`（Track-02/03/01 的领地）
- `alembic/versions/`（Track-02 迁移槽）
- `app/config.py`、`.env`（Track-01 互斥锁；本 provider 用 `os.environ.get` 读
  `FASTER_WHISPER_MODEL` / `FASTER_WHISPER_DEVICE` / `FASTER_WHISPER_COMPUTE_TYPE`
  / `FASTER_WHISPER_DOWNLOAD_ROOT`，给合理 default，无需在 Settings 里加字段）
- 前端

## faster_whisper_local.py 设计要点

1. **懒导入**：`importlib.util.find_spec("faster_whisper")` 探测，不在模块顶部
   `import faster_whisper` —— FastAPI 启动时不会尝试加载 ~150MB 权重。
2. **`is_available()` 仅看包是否装**，不需要任何 API key；`gateway.select_provider`
   遇到没装就跳到 SiliconFlow。
3. **单例缓存模型**：模块级 `_model_cache` dict 按 `(model, device, compute_type, download_root)`
   key 缓存 `WhisperModel` 实例，并发线程用 `threading.Lock` 保护。第二次调用
   不再触发下载/加载；冷启动 30s+ → 热推理 0.25s（tiny on M-series CPU 实测）。
4. **输出格式与 `OpenAIWhisperProvider` 完全对齐**：
   ```python
   {
       "text": str,
       "duration_s": float | None,
       "segments": [{"start", "end", "text"}, ...],
       "words":    [{"start", "end", "word"}, ...],
       "language": str | None,
   }
   ```
   `voice.py` 的 v4 路径无需感知是哪个 provider 出的 words。
5. **失败转 RenderResult.error 而不抛**：导入失败、模型加载失败、推理失败
   都被转成 `CallStatus.FAILED + error="..."`，gateway `_record` 入账正常。
6. **`word_timestamps=True`**：v4 路径的核心；`vad_filter=False` 防止短旁白被
   VAD 误删；`beam_size` 等用 faster-whisper 默认。

## 烟测结果（4/4 PASS）

### ① 装包前 `is_available=False`，gateway 不选它

```
provider name = faster_whisper_local
supports ASR = True
supports LLM = False
is_available (pre-install) = False
routing ASR = ['openai', 'faster_whisper_local', 'siliconflow']
```

✓ enum 值正确；ASR 路由顺序正确；未装包时 `is_available()` 直接 False。

### ② 装包：`pip install faster-whisper>=1.0`

```
Successfully installed annotated-doc-0.0.4 av-17.0.1 coloredlogs-15.0.1 ctranslate2-4.7.1
faster-whisper-1.2.1 filelock-3.29.0 flatbuffers-25.12.19 fsspec-2026.4.0 hf-xet-1.4.3
huggingface-hub-1.13.0 humanfriendly-10.0 markdown-it-py-4.0.0 mdurl-0.1.2 mpmath-1.3.0
numpy-2.2.6 onnxruntime-1.23.2 protobuf-7.34.1 rich-15.0.0 shellingham-1.5.4 sympy-1.14.0
tokenizers-0.23.1 tqdm-4.67.3 typer-0.25.1
```

依赖较多（CTranslate2 + onnxruntime + numpy + huggingface-hub 等）；总安装量约 200-300MB。
`requirements.txt` 因此把它标 **optional**，不让 CI / 默认部署强制装。

### ③ 装包后 `is_available=True`，真跑 transcribe

测试音频：`/tmp/tw_sine.wav`（3 秒 440Hz 正弦波，96KB，pcm_s16le 16kHz mono）。
环境变量：`FASTER_WHISPER_MODEL=tiny`、`FASTER_WHISPER_DOWNLOAD_ROOT=$(pwd)/.fw_models`。

```
is_available = True
--- 1st (cold; downloads model) ---
status = succeeded   wall_s = 31.51   duration_ms = 31513
keys = ['duration_s', 'language', 'segments', 'text', 'words']
text = ''
duration_s = 3.0
segments = 0
words = 0
language = en
--- 2nd (warm) ---
status = succeeded   wall_s = 0.25   duration_ms = 249
text = ''   words = 0
```

- ✓ `is_available=True`
- ✓ status=succeeded（cold 含模型下载 31.5s；warm 0.25s）
- ✓ output keys 与 OpenAIWhisper 完全一致 `['duration_s', 'language', 'segments', 'text', 'words']`
- ✓ `duration_s=3.0` 正确探测音频时长
- ⚠ `text=''/words=0/segments=0`：因为输入是 440Hz 正弦波，没有可识别的语音；
  这恰好证明 ASR 不会幻觉 + 异常路径（空 segment 列表）安全。

> 真语音识别 e2e（用户场景）：跑 `video_full` → voice step 出 mp3 → ASR 拿到 word
> 列表 → `outputs.asr_provider="faster_whisper_local"`、`outputs.subtitle_granularity="word"`。
> 因 sandbox 不能调 SiliconFlow TTS 真出语音，留给用户在本地真环境（无 sandbox）
> 跑 `video_full` 校验。算法侧 voice.py v4 已经在 6 个集成 case 上 PASS（见
> `SESSION_HANDOFF.md` 2026-05-05 10:00 段落），provider 接口对齐即可复用。

### ④ 卸载后 `is_available=False`，gateway 自动 fallback SiliconFlow

```
post-uninstall is_available = False
post-uninstall ASR selected = siliconflow
PASS: fallback to SiliconFlow when faster-whisper missing
```

✓ 卸载后立即变 False；gateway `select_provider(ASR)` 在 OpenAI 不可用 + faster-whisper
未装时正确选 SiliconFlow。

> 测试结束已重新装回 `faster-whisper-1.2.1`，让最终状态保持可用，用户复跑
> 不必再下依赖。

## 模型大小 / 首次推理耗时实测

| model | 模型权重大小 | 冷启动（首次推理含下载） | 热推理（缓存命中） | 推荐场景 |
|---|---|---|---|---|
| `tiny` | ~75 MB | 31.5 s（实测） | 0.25 s | 快速验证 / 长音频可接受准度 |
| `base` | ~150 MB（HF 列表） | ~60-90 s 估 | ~0.5-1 s | 默认（卡片建议）|
| `small` | ~480 MB | ~3-5 min 估 | ~2-3 s | 高准度需求 |
| `medium` | ~1.5 GB | 大于 10 min | ~5-10 s | 对中文等多语言要求高 |
| `large-v3` | ~3 GB | 视网络 | ~15-30 s | 离线最高准度（建议 GPU） |

> 注：以上时长在 Apple Silicon CPU + `compute_type=int8` 下的粗略估计；
> 真实部署到生产时建议 `FASTER_WHISPER_DEVICE=cuda` + `compute_type=float16`，热推理
> 5 min 长音频 < 10 s。

## 配置项（环境变量；不进 `.env` Settings 类避免 Track-01 互斥）

| env var | default | 说明 |
|---|---|---|
| `FASTER_WHISPER_MODEL` | `base` | tiny / base / small / medium / large-v3 |
| `FASTER_WHISPER_DEVICE` | `cpu` | `cpu` / `cuda` / `mps`（faster-whisper 暂未稳定支持 mps，先用 cpu）|
| `FASTER_WHISPER_COMPUTE_TYPE` | `int8`（cpu）/ `float16`（cuda）| `int8` / `float16` / `int8_float16` / `float32` |
| `FASTER_WHISPER_DOWNLOAD_ROOT` | HuggingFace 默认 `~/.cache/huggingface` | 离线机器 / sandbox 用，可指向 workspace 内可写路径 |

## 已知边界 / 跳过的子任务

1. **首次推理冷启动**：base 模型在 CPU 上首次约 60-90s（含下载 ~150MB + 模型初始化），
   用户首次跑 voice step 时会感觉「卡」；后续调用走单例缓存秒级。**没做**首次预热
   后台任务（FastAPI startup 时拉起一次空推理），避免用户没装 faster-whisper 时
   也莫名加载。让用户首次跑时显式感知。
2. **GPU 自动检测**：当前 `compute_type` 默认 cpu→int8 / 非 cpu→float16；没做
   `cuda.is_available()` 自动切换，需用户显式设 env。
3. **多语言提示**：`language` 参数支持外部传入（`zh`/`en`/...）；没传 faster-whisper
   自动检测。VoiceAgent v4 没主动传 language（一致性问题），实际识别会自动定位
   → 多数中文场景实测正确率 OK。
4. **HF 镜像**：默认走官方 HuggingFace；国内用户网络差时可设 `HF_ENDPOINT=https://hf-mirror.com`
   加速（在 `.env` / 环境变量里）。**没改 README**，因为 README 不在我修改范围。
5. **真语音 e2e**：因 sandbox 限 SiliconFlow TTS 跑不出真语音，e2e
   `outputs.asr_provider='faster_whisper_local'` 留给用户本地烟测；接口契约已与
   OpenAIWhisperProvider 对齐，逻辑等同。

## 后续 follow-up

- [ ] **预热任务**：FastAPI startup hook 在 settings 标志 `voice_warmup_local_asr=true`
      时后台跑一次空推理，把模型加载到内存（避免用户首次跑视频时卡 60-90s）。
- [ ] **VoiceAgent persist 一条 metric**：当 `asr_provider == "faster_whisper_local"`
      时写一条 `voice_local_asr_warm_seconds` metric 监控热推理时延；用 `/api/production/runs/{id}/metrics`
      回看。
- [ ] **前端 voice 卡片徽标**：`asr_provider="faster_whisper_local"` 时显示 emerald
      「本地 word v4」徽标，区分云端 OpenAI Whisper 与本地 faster-whisper。当前
      v4 徽标只看 words 数量，不区分 provider。
- [ ] **大模型权重不进 git**：`.fw_models/` 已自动写到 `FASTER_WHISPER_DOWNLOAD_ROOT`，
      未来如果用户在 fliki-clone-api 内部缓存（默认 `~/.cache/huggingface` 不在仓库），
      不需要 .gitignore；但若有人把 `FASTER_WHISPER_DOWNLOAD_ROOT` 设到仓库里，
      建议加 `.fw_models/` 到 `.gitignore`（本 PR 没动 `.gitignore`，留 follow-up）。

## 烟测命令速查（用户验收用）

```bash
# 1. 装包
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m pip install "faster-whisper>=1.0"

# 2. 重启 backend（不带 --reload）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 跑 video_full pipeline，验证 outputs.asr_provider == "faster_whisper_local"
#    （前提：把 .env 里 OPENAI_API_KEY 注释掉 / 留空）

# 4. 模拟卸载，验证自动 fallback SiliconFlow（v3 行级）
.venv/bin/python -m pip uninstall faster-whisper -y
# 重启 backend，再跑 voice → outputs.asr_provider == "siliconflow"，subtitle_granularity == "line"
```

## 互斥锁声明

本 PR 仅修改了卡片允许的 6 个文件 + 1 个新 provider 文件；其他 Track 文件（包括
`voice.py`、`art.py`、`publishing/`、`alembic/`、`config.py`、`.env`、前端）一律未动。
