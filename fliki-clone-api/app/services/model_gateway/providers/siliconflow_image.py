"""硅基流动 文生图 provider（Flux / SD / Kolors 等）。

OpenAI 兼容 `/images/generations` 接口；同步返回结果，无需轮询。

`RenderRequest.params`：
- `prompt`            : 必填
- `negative_prompt`   : 可选
- `image_size`        : 可选（如 `1024x1024`、`1024x1792`）；按 aspect 自动推断
- `aspect_ratio`      : 可选；`9:16` / `16:9` / `1:1` / `4:5`
- `n`                 : 默认 1
- `seed`              : 可选
- `guidance_scale`    : 可选
- `num_inference_steps`: 可选

返回 `RenderResult.output = {"image_url": str, "image_urls": [str, ...], "image_size": "WxH"}`。
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


# 不同模型对 image_size 的合法值约束不同；统一抽象成 aspect → 常见可用尺寸的映射
_ASPECT_TO_SIZE: dict[str, str] = {
    "1:1": "1024x1024",
    "16:9": "1024x576",
    "9:16": "576x1024",
    "4:5": "896x1120",
    "5:4": "1120x896",
    "4:3": "1024x768",
    "3:4": "768x1024",
}


class SiliconFlowImageProvider(BaseProvider):
    name = ProviderName.SILICONFLOW

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.GENERATE_IMAGE

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
        prompt = str(params.get("prompt") or "").strip()
        if not prompt:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing prompt",
            )

        primary_model = (
            request.model_hint or params.get("model") or settings.image_model
        )
        # 同 TTS：SiliconFlow 不时下线模型（fish-speech / Flux schnell 已踩过）；
        # 命中 model_disabled / 4xx 时降级到长期稳定的 Kolors。
        fallback_model = "Kwai-Kolors/Kolors"
        model_chain: list[str] = [primary_model]
        if fallback_model and fallback_model != primary_model:
            model_chain.append(fallback_model)

        n = int(params.get("n") or 1)
        image_size = _resolve_image_size(params)
        last_error: str | None = None
        last_duration_ms = 0

        for idx, model in enumerate(model_chain):
            body: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "image_size": image_size,
                "batch_size": n,
            }
            if params.get("negative_prompt"):
                body["negative_prompt"] = str(params["negative_prompt"])[:1000]
            for k in ("seed", "guidance_scale", "num_inference_steps"):
                if k in params and params[k] is not None:
                    body[k] = params[k]

            timeout_s = request.timeout_s or 120.0
            started = time.time()
            try:
                resp = requests.post(
                    f"{settings.siliconflow_base_url}/images/generations",
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout_s,
                )
            except requests.Timeout:
                last_duration_ms = int((time.time() - started) * 1000)
                return RenderResult(
                    status=CallStatus.TIMEOUT,
                    provider=self.name,
                    model=model,
                    duration_ms=last_duration_ms,
                    error="upstream timeout",
                )
            except Exception as exc:
                last_duration_ms = int((time.time() - started) * 1000)
                last_error = str(exc)
                continue

            last_duration_ms = int((time.time() - started) * 1000)

            if resp.status_code == 200:
                try:
                    payload = resp.json()
                except Exception as exc:
                    last_error = f"invalid json: {exc}"
                    continue
                urls = _extract_image_urls(payload)
                if not urls:
                    last_error = "response did not contain image url"
                    continue
                status = CallStatus.SUCCEEDED if idx == 0 else CallStatus.DEGRADED
                return RenderResult(
                    status=status,
                    output={
                        "image_url": urls[0],
                        "image_urls": urls,
                        "image_size": image_size,
                        "fallback_used": idx > 0,
                    },
                    provider=self.name,
                    model=model,
                    duration_ms=last_duration_ms,
                )

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
                "SiliconFlow image model %s rejected (%s); falling back",
                model,
                err_body,
            )

        return RenderResult(
            status=CallStatus.FAILED,
            provider=self.name,
            model=model_chain[-1],
            duration_ms=last_duration_ms,
            error=last_error or "all image models failed",
        )


def _should_fallback(status_code: int, body: str) -> bool:
    """与 TTS provider 同语义：模型被禁 / 不存在时换模型，认证类直接失败。"""

    if status_code in (401, 403):
        return "model" in body.lower() or "disabled" in body.lower()
    if status_code in (404, 422):
        return True
    return False


def _resolve_image_size(params: dict[str, Any]) -> str:
    """优先 `image_size`，其次 `aspect_ratio`，否则 1024x1024。"""

    explicit = str(params.get("image_size") or "").strip()
    if explicit:
        return explicit
    aspect = str(params.get("aspect_ratio") or "").strip()
    if aspect in _ASPECT_TO_SIZE:
        return _ASPECT_TO_SIZE[aspect]
    return "1024x1024"


def _extract_image_urls(payload: Any) -> list[str]:
    """SiliconFlow / OpenAI 兼容回包结构：`{ "data": [{"url": "..."}] }`，
    部分模型回 `{ "images": [{"url": "..."}] }`，都尝试。"""

    out: list[str] = []
    if not isinstance(payload, dict):
        return out
    for key in ("data", "images"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("image_url")
                    if isinstance(url, str) and url:
                        out.append(url)
                elif isinstance(item, str):
                    out.append(item)
    return out
