"""SiliconFlow ASR provider（OpenAI 兼容 `/audio/transcriptions`）。

主要服务于 VoiceAgent v2 字幕对齐：把 TTS 出来的旁白音频拿回真实播放时长 + 可选
segment-level 时间戳，让 EditAgent 烧出来的字幕跟旁白对得上（v1 是按 shots.duration_s
均分，loop 之后会漂）。

`RenderRequest.params` 字段：
- `audio_bytes`        : 必填，bytes / bytearray，音频原始字节
- `audio_format`       : 可选，默认 "mp3"，会作为 multipart 上传文件名后缀
- `model`              : 可选，覆盖 `settings.asr_model`
- `language`           : 可选，例如 "zh" / "en" / "ja"；多语 SenseVoice 自动检测
- `response_format`    : 可选，默认 "verbose_json"（拿 segments + duration）

返回 `RenderResult.output`:
    {
        "text": str,                 # 完整识别文本
        "duration_s": float | None,  # 音频真实时长（来自 verbose_json 或 ffprobe 兜底）
        "segments": list[dict] | [], # [{start, end, text}]
        "words":    list[dict] | [], # [{start, end, word}]（whisper 系才有；SenseVoice 一般没有）
        "language": str | None,
    }

设计：
- SenseVoice 在 SiliconFlow 上的 `verbose_json` 可能只返回 text；缺 duration 时调用方
  会用 ffprobe 兜底（VoiceAgent v2 内做），provider 不做这件事，避免依赖 ffmpeg。
- 上传 multipart 而不是 base64：SiliconFlow `/audio/transcriptions` 走 OpenAI 同款契约。
- 不直接抛异常；用 RenderResult.error 透传给 gateway 记账。
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


class SiliconFlowASRProvider(BaseProvider):
    name = ProviderName.SILICONFLOW

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.ASR

    def is_available(self) -> bool:
        return bool(get_settings().siliconflow_api_key)

    def call(self, request: RenderRequest) -> RenderResult:
        settings = get_settings()
        api_key = settings.siliconflow_api_key
        if not api_key:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing siliconflow_api_key",
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
            request.model_hint or params.get("model") or settings.asr_model
        )
        audio_format = (params.get("audio_format") or "mp3").lower()
        response_format = params.get("response_format") or "verbose_json"
        language = params.get("language")

        files = {
            # 文件名扩展名给后端识别 mime；content 用 bytes
            "file": (
                f"narration.{audio_format}",
                io.BytesIO(bytes(audio)),
                _content_type_for(audio_format),
            ),
        }
        data: dict[str, str] = {
            "model": str(model),
            "response_format": str(response_format),
        }
        if language:
            data["language"] = str(language)

        timeout_s = request.timeout_s or 60.0
        started = time.time()
        try:
            resp = requests.post(
                f"{settings.siliconflow_base_url}/audio/transcriptions",
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

        # verbose_json 返回 dict；text 返回 str
        text_body = resp.text
        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = {"text": text_body}

        if isinstance(payload, dict):
            text = str(payload.get("text") or "").strip()
            duration_s = _to_float_or_none(payload.get("duration"))
            segments = _normalise_segments(payload.get("segments"))
            words = _normalise_words(payload.get("words"))
            lang = payload.get("language")
        else:
            # 非预期：list / 其他；当 raw 字符串处理
            text = str(text_body or "").strip()
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


__all__ = ["SiliconFlowASRProvider"]
