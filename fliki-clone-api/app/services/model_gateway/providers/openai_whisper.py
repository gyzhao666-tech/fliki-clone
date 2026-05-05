"""OpenAI Whisper ASR provider（真 OpenAI 端点，与 SiliconFlow 兼容路径并存）。

设计意图
--------
SiliconFlow 的 SenseVoiceSmall 不返 `verbose_json` 时间戳，VoiceAgent v3 只能走
ffprobe 拿真实音频时长 + 算法做行级细切。要做真 word-level / segment-level 强
对齐（卡拉 OK 高亮、按 word 边界拆字幕），目前最稳的端点是 OpenAI Whisper-1
（`https://api.openai.com/v1/audio/transcriptions`）。

激活条件：
- `.env` 里配 `OPENAI_API_KEY` 即可；没配则 `is_available()=False`，gateway
  会自动 fallback 到 SiliconFlow ASR。
- 不在 cost 表里硬塞单价，用 OpenAI 公开报价：whisper-1 ≈ $0.006/min。

`RenderRequest.params` 字段（与 SiliconFlowASRProvider 完全一致）：
- `audio_bytes` / `audio_format` / `model` / `language` / `response_format`

返回 `RenderResult.output`：
    {
        "text": str,
        "duration_s": float | None,
        "segments": list[dict],   # whisper-1 verbose_json 标配
        "words": list[dict],      # 加 timestamp_granularities=[word] 才有
        "language": str | None,
    }
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Any

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAIWhisperProvider(BaseProvider):
    name = ProviderName.OPENAI

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.ASR

    def is_available(self) -> bool:
        return bool(get_settings().openai_api_key)

    def call(self, request: RenderRequest) -> RenderResult:
        settings = get_settings()
        api_key = settings.openai_api_key
        if not api_key:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing openai_api_key",
            )

        params: dict[str, Any] = dict(request.params or {})
        audio = params.get("audio_bytes")
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing audio_bytes",
            )

        model = (
            request.model_hint or params.get("model") or settings.openai_asr_model
        )
        audio_format = (params.get("audio_format") or "mp3").lower()
        response_format = params.get("response_format") or "verbose_json"
        language = params.get("language")

        files = {
            "file": (
                f"narration.{audio_format}",
                io.BytesIO(bytes(audio)),
                _content_type_for(audio_format),
            ),
        }
        # whisper-1 拿 word-level：必须显式开 word granularity（segment 默认带）
        # data 用 list[tuple] 让 requests 把同名 key 编码成数组
        data: list[tuple[str, str]] = [
            ("model", str(model)),
            ("response_format", str(response_format)),
            ("timestamp_granularities[]", "segment"),
            ("timestamp_granularities[]", "word"),
        ]
        if language:
            data.append(("language", str(language)))

        timeout_s = request.timeout_s or 60.0
        started = time.time()
        try:
            resp = requests.post(
                f"{settings.openai_base_url}/audio/transcriptions",
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=timeout_s,
            )
        except requests.Timeout:
            return RenderResult(
                status=CallStatus.TIMEOUT,
                provider=self.name,
                model=model,
                duration_ms=int((time.time() - started) * 1000),
                error="upstream timeout",
            )
        except Exception as exc:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                duration_ms=int((time.time() - started) * 1000),
                error=str(exc),
            )

        elapsed_ms = int((time.time() - started) * 1000)

        if resp.status_code != 200:
            err_body = resp.text[:200]
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                duration_ms=elapsed_ms,
                error=f"http {resp.status_code}: {err_body}",
            )

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = {"text": resp.text}

        if isinstance(payload, dict):
            text = str(payload.get("text") or "").strip()
            duration_s = _to_float_or_none(payload.get("duration"))
            segments = _normalise_segments(payload.get("segments"))
            words = _normalise_words(payload.get("words"))
            lang = payload.get("language")
        else:
            text = ""
            duration_s = None
            segments = []
            words = []
            lang = None

        return RenderResult(
            status=CallStatus.SUCCEEDED,
            output={
                "text": text,
                "duration_s": duration_s,
                "segments": segments,
                "words": words,
                "language": lang,
            },
            provider=self.name,
            model=model,
            duration_ms=elapsed_ms,
        )


def _content_type_for(fmt: str) -> str:
    f = (fmt or "").lower()
    if f in ("mp3", "mpga"):
        return "audio/mpeg"
    if f == "wav":
        return "audio/wav"
    if f == "m4a":
        return "audio/mp4"
    if f == "ogg":
        return "audio/ogg"
    if f == "flac":
        return "audio/flac"
    return "application/octet-stream"


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return f if f > 0 else None
    except Exception:
        return None


def _normalise_segments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for seg in value:
        if not isinstance(seg, dict):
            continue
        start = _to_float_or_none(seg.get("start"))
        end = _to_float_or_none(seg.get("end"))
        text = str(seg.get("text") or "").strip()
        if start is None or end is None or end <= start:
            continue
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return out


def _normalise_words(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for w in value:
        if not isinstance(w, dict):
            continue
        start = _to_float_or_none(w.get("start"))
        end = _to_float_or_none(w.get("end"))
        word = str(w.get("word") or w.get("text") or "").strip()
        if start is None or end is None or end <= start or not word:
            continue
        out.append({"start": round(start, 3), "end": round(end, 3), "word": word})
    return out


__all__ = ["OpenAIWhisperProvider"]
