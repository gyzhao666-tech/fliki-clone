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
- `image_url`          : 可选（v4 IP-Adapter）；传入参考图（通常是 ArtAgent 已落库的
                         `outputs.character_anchor.url`）作为 IP-Adapter / image-to-image
                         主参考帧。当上游 SiliconFlow 模型不支持 image_url 时本 provider
                         自动剥离该参数重试同一模型并把 `ip_adapter_used=False` +
                         `ip_adapter_degrade_reason` 写回 output；不影响调用 ok 状态。

返回 `RenderResult.output = {"image_url": str, "image_urls": [str, ...], "image_size": "WxH",
                                "ip_adapter_used": bool, "ip_adapter_degrade_reason"?: str}`。

注：v4 IP-Adapter 真接入策略
---------------------------
SiliconFlow 当前公开的 `/images/generations` 端点对 `image` / `image_url` 等输入参考
图字段并未官方文档化，且在不同模型（Kolors / FLUX / SDXL）下行为不一致。本 provider
按以下顺序尝试（**保证 caller 永远拿得到一张图，最差降级为纯 prompt**）：

1. 若 caller 传 `image_url`：
   a. 若环境变量 `SILICONFLOW_KOLORS_IP_MODEL` 存在 → 优先路由到该模型（认为其支持 IP）
   b. 否则使用 `request.model_hint` / `settings.image_model`（即 Kwai-Kolors/Kolors）；
      在 body 中同时塞 `image` + `image_url` 两个常见 key（不同后端模型适配不同）
   c. 命中 200 → `ip_adapter_used=True`
   d. 命中 4xx 且响应体含 image-参数相关报错（`image`/`init_image`/`unsupported`/
      `unknown parameter`）→ **剥离 image_url 重试一次相同模型**，标
      `ip_adapter_used=False` + `ip_adapter_degrade_reason="silently dropped image_url:
      <reason>"`，仍按原模型 SUCCEEDED 返回（v3 prompt-only 行为）

2. 不传 image_url：保持 v3 行为不变。

未来 SiliconFlow 正式上线 Kolors-IP / Flux Redux 端点时，把环境变量
`SILICONFLOW_KOLORS_IP_MODEL` 指向官方 model id 即可激活 IP-Adapter；不需要改业务代码。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


# 报错体里出现以下任一关键词时，认为是「模型不支持 image_url 这类输入参数」，
# 触发剥离 image_url 重试。其他 4xx（如 prompt 违规）走原降级链。
_IMAGE_PARAM_REJECT_HINTS: tuple[str, ...] = (
    "image_url",
    "init_image",
    "image input",
    "unsupported parameter",
    "unknown parameter",
    "invalid parameter: image",
    "ip_adapter",
    "reference image",
)


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

        # v4 IP-Adapter：caller 传了参考图就尝试把它喂给模型；不支持时会自动剥离重试。
        image_url = str(params.get("image_url") or "").strip() or None
        kolors_ip_model = os.getenv("SILICONFLOW_KOLORS_IP_MODEL", "").strip() or None

        if image_url and kolors_ip_model:
            # 显式配了 Kolors-IP 模型 id：把它放主选，认为该模型支持 image_url
            primary_model = kolors_ip_model
        else:
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
        # 跨模型记录：本次调用最终是否真把 image_url 喂给了上游模型
        ip_adapter_used = False
        ip_adapter_degrade_reason: str | None = None

        for idx, model in enumerate(model_chain):
            # 每个模型尝试两轮：第一轮带 image_url（若有），4xx 命中 image-参数报错时
            # 第二轮剥离 image_url 重试同模型。这样 caller 永远拿得到一张图，最差降级为
            # 纯 prompt（v3 行为）。
            attempt_image_url: str | None = image_url
            for attempt in (0, 1):
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
                if attempt_image_url:
                    # 不同 SF 后端模型对参考图字段命名不一致；同时塞 `image` / `image_url`
                    # 让兼容性最大化。模型不识别多余 key 时通常会忽略；不忽略时上面的
                    # _is_image_param_reject 兜底剥离重试。
                    body["image"] = attempt_image_url
                    body["image_url"] = attempt_image_url

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
                    break  # 网络异常不重试同模型，直接换下一个 model

                last_duration_ms = int((time.time() - started) * 1000)

                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except Exception as exc:
                        last_error = f"invalid json: {exc}"
                        break
                    urls = _extract_image_urls(payload)
                    if not urls:
                        last_error = "response did not contain image url"
                        break
                    if attempt_image_url:
                        ip_adapter_used = True
                    status = CallStatus.SUCCEEDED if idx == 0 else CallStatus.DEGRADED
                    out: dict[str, Any] = {
                        "image_url": urls[0],
                        "image_urls": urls,
                        "image_size": image_size,
                        "fallback_used": idx > 0,
                        "ip_adapter_used": ip_adapter_used,
                    }
                    if ip_adapter_degrade_reason:
                        out["ip_adapter_degrade_reason"] = ip_adapter_degrade_reason
                    return RenderResult(
                        status=status,
                        output=out,
                        provider=self.name,
                        model=model,
                        duration_ms=last_duration_ms,
                    )

                err_body = resp.text[:200]
                last_error = f"http {resp.status_code}: {err_body}"

                # 4xx + image-参数报错 → 剥离 image_url 后重试同一模型一次（v4 → v3 降级）
                if (
                    attempt == 0
                    and attempt_image_url
                    and 400 <= resp.status_code < 500
                    and _is_image_param_reject(err_body)
                ):
                    ip_adapter_degrade_reason = (
                        f"silently dropped image_url: http {resp.status_code} {err_body[:120]}"
                    )
                    logger.warning(
                        "SiliconFlow image model %s rejected image_url (%s); retrying without IP-Adapter",
                        model,
                        err_body,
                    )
                    attempt_image_url = None
                    continue  # 重试同模型

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
                break  # 跳出 attempt 循环，换下一个 model

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


def _is_image_param_reject(body: str) -> bool:
    """response body 是否表明：upstream 拒绝是因为 image_url / 参考图相关参数不被识别。"""

    low = body.lower()
    return any(hint in low for hint in _IMAGE_PARAM_REJECT_HINTS)


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
