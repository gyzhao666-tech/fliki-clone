"""faster-whisper 本地 ASR provider（VoiceAgent v4 word-level 的离线 fallback）。

设计意图
--------
当用户没有 `OPENAI_API_KEY` 时，VoiceAgent v4 的 word-level 强对齐路径会塌成
v3 行级（SiliconFlow SenseVoice 不返 words）。本 provider 在本地用
faster-whisper（CTranslate2 加速的 Whisper）跑出 segment + word 时间戳，让
v4 word-level 字幕在完全离线 / 不付费 OpenAI 的情况下仍可用。

激活条件
~~~~~~~~
- 安装了 `faster-whisper` 包（`pip install faster-whisper`）。
- 系统能下载到模型权重（首次推理触发，约 ~150MB for `base`）。
- 没有任何 API key 要求；`is_available()` 仅取决于 import 是否成功。

路由位置
~~~~~~~~
gateway 默认 ASR 路由：`[OPENAI, FASTER_WHISPER_LOCAL, SILICONFLOW]`。
- 有 OpenAI key  → 走 OpenAI Whisper-1（云端 word-level，最准）
- 没 key + 装了 faster-whisper → 走本地（word-level，离线零成本）
- 都没有        → SiliconFlow SenseVoice（无 words，VoiceAgent 退到 v3 行级）

`RenderRequest.params`（与 OpenAIWhisperProvider / SiliconFlowASRProvider 一致）
- `audio_bytes`     : 必填，bytes / bytearray
- `audio_format`    : 可选，默认 "mp3"
- `model`           : 可选，覆盖 `FASTER_WHISPER_MODEL` env / "base"
- `language`        : 可选，例如 "zh" / "en"；不传 faster-whisper 自动检测
- `response_format` : 忽略（本 provider 总是返结构化 dict）

返回 `RenderResult.output`：
    {
        "text":       str,
        "duration_s": float | None,
        "segments":   list[{"start": float, "end": float, "text": str}],
        "words":      list[{"start": float, "end": float, "word": str}],
        "language":   str | None,
    }

模型 / 设备 / 精度配置（环境变量；`config.py` 走 Track-01 互斥锁，不能动）
- `FASTER_WHISPER_MODEL`        : 默认 "base"（~150MB）；可选 "tiny"/"small"/"medium"/"large-v3"
- `FASTER_WHISPER_DEVICE`       : 默认 "cpu"；GPU 用户可设 "cuda"
- `FASTER_WHISPER_COMPUTE_TYPE` : 默认 "int8"（CPU 最优）；GPU 设 "float16"/"int8_float16"
- `FASTER_WHISPER_DOWNLOAD_ROOT`: 可选，覆盖 HuggingFace 默认缓存目录

设计取舍
~~~~~~~~
- **懒导入 + 单例模型**：模块级 `import faster_whisper` 会让 fastapi 启动时
  阻塞下载模型；改为类内 `_load_model()` 首次 `call()` 触发，缺包时
  `is_available()` 直接 False，gateway 静默跳过。
- **输出格式与云端 OpenAIWhisperProvider 完全一致**：让 voice.py 的 v4 算法
  无需感知 provider 来源，`asr_provider` 字段直接落 `faster_whisper_local`。
- **不计费**：cost 表中 `(FASTER_WHISPER_LOCAL, ASR) = 0.0`；本地推理零外部
  成本，但确实占 CPU/RAM，调用方需自行感知首次冷启动延迟。
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
from typing import Any, Optional

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


_model_cache_lock = threading.Lock()
_model_cache: dict[tuple[str, str, str, Optional[str]], Any] = {}


def _has_faster_whisper() -> bool:
    """仅做 import 探测，不真正加载模型权重。"""
    try:
        import importlib

        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:  # pragma: no cover
        return False


def _resolve_settings(params: dict[str, Any]) -> tuple[str, str, str, Optional[str]]:
    model = (
        params.get("model")
        or os.environ.get("FASTER_WHISPER_MODEL")
        or "base"
    )
    device = (
        params.get("device")
        or os.environ.get("FASTER_WHISPER_DEVICE")
        or "cpu"
    )
    compute_type = (
        params.get("compute_type")
        or os.environ.get("FASTER_WHISPER_COMPUTE_TYPE")
        or ("int8" if device == "cpu" else "float16")
    )
    download_root = os.environ.get("FASTER_WHISPER_DOWNLOAD_ROOT") or None
    return str(model), str(device), str(compute_type), download_root


def _load_model(model: str, device: str, compute_type: str, download_root: Optional[str]):
    """单例缓存：相同 (model, device, compute_type, download_root) 复用。"""
    key = (model, device, compute_type, download_root)
    cached = _model_cache.get(key)
    if cached is not None:
        return cached
    with _model_cache_lock:
        cached = _model_cache.get(key)
        if cached is not None:
            return cached
        from faster_whisper import WhisperModel  # 懒导入

        logger.info(
            "faster_whisper: loading model=%s device=%s compute_type=%s (first call may download weights)",
            model, device, compute_type,
        )
        kwargs: dict[str, Any] = {"device": device, "compute_type": compute_type}
        if download_root:
            kwargs["download_root"] = download_root
        instance = WhisperModel(model, **kwargs)
        _model_cache[key] = instance
        return instance


class FasterWhisperLocalProvider(BaseProvider):
    name = ProviderName.FASTER_WHISPER_LOCAL

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.ASR

    def is_available(self) -> bool:
        return _has_faster_whisper()

    def call(self, request: RenderRequest) -> RenderResult:  # noqa: C901 (清晰主流程)
        if not _has_faster_whisper():
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="faster_whisper package not installed; pip install faster-whisper",
            )

        params: dict[str, Any] = dict(request.params or {})
        audio = params.get("audio_bytes")
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing audio_bytes",
            )

        model_name, device, compute_type, download_root = _resolve_settings(params)
        model_name = request.model_hint or model_name

        language = params.get("language")
        # faster-whisper 的 transcribe() 接 file-like / 路径 / numpy；用 BytesIO 最少 IO
        audio_io = io.BytesIO(bytes(audio))

        started = time.time()
        try:
            model_instance = _load_model(model_name, device, compute_type, download_root)
        except Exception as exc:
            logger.exception("faster_whisper: model load failed")
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model_name,
                duration_ms=int((time.time() - started) * 1000),
                error=f"model load failed: {exc}",
            )

        try:
            # word_timestamps=True 是拿到 word-level 的关键；
            # vad_filter 默认关掉避免对短音频误删；beam_size=5 保留 faster-whisper 默认。
            segments_iter, info = model_instance.transcribe(
                audio_io,
                language=language if language else None,
                word_timestamps=True,
                vad_filter=False,
            )
        except Exception as exc:
            logger.exception("faster_whisper: transcribe failed")
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model_name,
                duration_ms=int((time.time() - started) * 1000),
                error=f"transcribe failed: {exc}",
            )

        try:
            segments_norm: list[dict[str, Any]] = []
            words_norm: list[dict[str, Any]] = []
            text_pieces: list[str] = []

            for seg in segments_iter:
                seg_start = _to_float_or_none(getattr(seg, "start", None))
                seg_end = _to_float_or_none(getattr(seg, "end", None))
                seg_text = str(getattr(seg, "text", "") or "").strip()
                if seg_start is not None and seg_end is not None and seg_end > seg_start:
                    segments_norm.append(
                        {
                            "start": round(seg_start, 3),
                            "end": round(seg_end, 3),
                            "text": seg_text,
                        }
                    )
                    if seg_text:
                        text_pieces.append(seg_text)

                seg_words = getattr(seg, "words", None) or []
                for w in seg_words:
                    w_start = _to_float_or_none(getattr(w, "start", None))
                    w_end = _to_float_or_none(getattr(w, "end", None))
                    word_text = str(getattr(w, "word", "") or "").strip()
                    if (
                        w_start is None
                        or w_end is None
                        or w_end <= w_start
                        or not word_text
                    ):
                        continue
                    words_norm.append(
                        {
                            "start": round(w_start, 3),
                            "end": round(w_end, 3),
                            "word": word_text,
                        }
                    )
        except Exception as exc:
            logger.exception("faster_whisper: segments materialize failed")
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model_name,
                duration_ms=int((time.time() - started) * 1000),
                error=f"materialize failed: {exc}",
            )

        elapsed_ms = int((time.time() - started) * 1000)
        duration_s = _to_float_or_none(getattr(info, "duration", None))
        detected_language = getattr(info, "language", None) or None

        return RenderResult(
            status=CallStatus.SUCCEEDED,
            output={
                "text": " ".join(text_pieces).strip(),
                "duration_s": duration_s,
                "segments": segments_norm,
                "words": words_norm,
                "language": detected_language,
            },
            provider=self.name,
            model=model_name,
            duration_ms=elapsed_ms,
        )


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return f if f > 0 else None
    except Exception:
        return None


__all__ = ["FasterWhisperLocalProvider"]
