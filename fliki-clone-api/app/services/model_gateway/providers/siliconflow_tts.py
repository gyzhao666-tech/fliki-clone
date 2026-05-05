"""SiliconFlow TTS provider（OpenAI 兼容 `/audio/speech`）。

支持 Fish-Speech / CosyVoice 等模型；返回 mp3 字节，由调用方决定是否上传到 S3。

`RenderRequest.params` 字段：
- `text`        : 必填，要合成的文字
- `voice`       : 可选，voice ref，例如 `FunAudioLLM/CosyVoice2-0.5B:alex`；缺省走 `default_voice`
- `model`       : 可选，覆盖 `settings.tts_model`
- `speed`       : 可选 float，默认 1.0
- `format`      : 可选，默认 `mp3`
- `gain`        : 可选，默认 0.0
- `default_voice`: 可选，VoiceAgent 兜底：当 brief / shot 没指定 voice 时使用

返回 `RenderResult.output = {"audio_bytes": bytes, "format": "mp3"}`。
不直接上传 S3，避免与业务侧"按 step 命名 key"耦合；上传逻辑在 VoiceAgent 中。
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


class SiliconFlowTTSProvider(BaseProvider):
    name = ProviderName.SILICONFLOW

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.TTS

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
        text = str(params.get("text") or "").strip()
        if not text:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing text",
            )

        primary_model = (
            request.model_hint or params.get("model") or settings.tts_model
        )
        # SiliconFlow 不时下线模型（如 fish-speech）；命中 model_disabled / 4xx 后自动降级。
        fallback_model = "FunAudioLLM/CosyVoice2-0.5B"
        model_chain: list[str] = [primary_model]
        if fallback_model and fallback_model != primary_model:
            model_chain.append(fallback_model)

        last_error: str | None = None
        last_duration_ms = 0
        for idx, model in enumerate(model_chain):
            voice = (
                params.get("voice")
                or params.get("default_voice")
                or _default_voice_for(model)
            )
            if not voice:
                last_error = "missing voice (set params.voice or pass default_voice)"
                continue

            body = {
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": params.get("format") or "mp3",
                "speed": float(params.get("speed", 1.0)),
                "gain": float(params.get("gain", 0.0)),
            }

            timeout_s = request.timeout_s or 60.0
            started = time.time()
            try:
                resp = requests.post(
                    f"{settings.siliconflow_base_url}/audio/speech",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout_s,
                )
            except requests.Timeout:
                last_duration_ms = int((time.time() - started) * 1000)
                last_error = "upstream timeout"
                # 超时一般是网络问题，fallback 大概率也会超时，直接返回
                return RenderResult(
                    status=CallStatus.TIMEOUT,
                    provider=self.name,
                    model=model,
                    duration_ms=last_duration_ms,
                    error=last_error,
                )
            except Exception as exc:
                last_duration_ms = int((time.time() - started) * 1000)
                last_error = str(exc)
                continue

            last_duration_ms = int((time.time() - started) * 1000)

            if resp.status_code == 200:
                audio_bytes = resp.content
                if not audio_bytes:
                    last_error = "empty audio body"
                    continue
                status = CallStatus.SUCCEEDED if idx == 0 else CallStatus.DEGRADED
                return RenderResult(
                    status=status,
                    output={
                        "audio_bytes": audio_bytes,
                        "format": body["response_format"],
                        "voice": voice,
                        "char_count": len(text),
                        "fallback_used": idx > 0,
                    },
                    provider=self.name,
                    model=model,
                    duration_ms=last_duration_ms,
                )

            # 非 200：记下错误，看是否值得 fallback。
            err_body = resp.text[:200]
            last_error = f"http {resp.status_code}: {err_body}"
            if not _should_fallback(resp.status_code, err_body):
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    model=model,
                    duration_ms=last_duration_ms,
                    error=last_error,
                )
            logger.warning(
                "SiliconFlow TTS model %s rejected (%s); falling back",
                model,
                err_body,
            )

        return RenderResult(
            status=CallStatus.FAILED,
            provider=self.name,
            model=model_chain[-1],
            duration_ms=last_duration_ms,
            error=last_error or "all TTS models failed",
        )


def _should_fallback(status_code: int, body: str) -> bool:
    """是否值得换模型重试。

    典型可换模型：模型禁用 / 不存在 / 不支持。
    认证 / 鉴权 / 限流类错误换模型也救不了，直接失败。
    """
    if status_code in (401, 403):
        # 403 + Model disabled 是 SiliconFlow 关闭模型时的回包；其它 403 多半是 auth。
        return "model" in body.lower() or "disabled" in body.lower()
    if status_code in (404, 422):
        return True
    return False


def _default_voice_for(model: str) -> str:
    """SiliconFlow 不同 TTS 模型有自己的内置 voice 命名空间，给一个最常见的兜底。"""

    m = (model or "").lower()
    if "cosyvoice" in m:
        return "FunAudioLLM/CosyVoice2-0.5B:alex"
    if "fish-speech" in m:
        return "fishaudio/fish-speech-1.5:alex"
    return ""
