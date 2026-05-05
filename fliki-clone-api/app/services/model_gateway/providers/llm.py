"""OpenAI 兼容的 LLM provider。

当前指向 SiliconFlow（DeepSeek-V3 等），未来同一个 provider 可服务任何 OpenAI 兼容端点。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from app.config import get_settings

from ..types import CallStatus, ModelAction, ProviderName, RenderRequest, RenderResult
from .base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAICompatLLMProvider(BaseProvider):
    """通过 OpenAI 兼容 `chat/completions` 接口调用 LLM。

    `RenderRequest.params` 支持的字段：
    - `messages`: list[dict]，OpenAI 格式
    - `model`: 覆盖 settings 中的默认 model
    - `temperature`: 默认 0.6
    - `max_tokens`: 默认 1024
    - `response_format`: "json_array" 时会从响应中提取首段 JSON 数组并解析为 list[Any]
    """

    name = ProviderName.SILICONFLOW

    def supports(self, action: ModelAction) -> bool:
        return action == ModelAction.LLM

    def is_available(self) -> bool:
        return bool(get_settings().siliconflow_api_key)

    def call(self, request: RenderRequest) -> RenderResult:  # noqa: C901
        settings = get_settings()
        api_key = settings.siliconflow_api_key
        if not api_key:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing siliconflow_api_key",
            )

        params = dict(request.params or {})
        messages = params.get("messages")
        if not messages:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                error="missing messages",
            )

        model = request.model_hint or params.get("model") or settings.llm_model
        temperature = float(params.get("temperature", 0.6))
        max_tokens = int(params.get("max_tokens", 1024))
        response_format = params.get("response_format")
        timeout_s = request.timeout_s or 60.0

        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        started = time.time()
        try:
            resp = requests.post(
                f"{settings.siliconflow_base_url}/chat/completions",
                json=body,
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

        duration_ms = int((time.time() - started) * 1000)
        if resp.status_code != 200:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                duration_ms=duration_ms,
                error=f"http {resp.status_code}: {resp.text[:200]}",
            )

        try:
            payload = resp.json()
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            return RenderResult(
                status=CallStatus.FAILED,
                provider=self.name,
                model=model,
                duration_ms=duration_ms,
                error=f"invalid response: {exc}",
            )

        output: Any = content
        if response_format == "json_array":
            output = _extract_json_array(content)
            if output is None:
                return RenderResult(
                    status=CallStatus.FAILED,
                    provider=self.name,
                    model=model,
                    duration_ms=duration_ms,
                    error="response did not contain a JSON array",
                    raw=content,
                )

        return RenderResult(
            status=CallStatus.SUCCEEDED,
            output=output,
            provider=self.name,
            model=model,
            duration_ms=duration_ms,
            raw=content,
        )


def _extract_json_array(content: str) -> list[Any] | None:
    """从 LLM 自由文本中尽力提取首段 JSON 数组。

    兼容 ```json ... ``` / ```...``` 围栏与对象内嵌数组：先去围栏，再用括号计数找到
    第一个 `[` 与对应的闭合 `]`，避免非贪婪正则在嵌套结构上失败。
    """

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
        # 去掉结尾可能残留的 ```
        if text.endswith("```"):
            text = text[:-3].strip()

    start = text.find("[")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    parsed = json.loads(snippet)
                except Exception:
                    return None
                return parsed if isinstance(parsed, list) else None
    return None
