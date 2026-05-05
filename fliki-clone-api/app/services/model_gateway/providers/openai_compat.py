"""OpenAI 兼容协议的 LLM provider（v1 主用于 SiliconFlow）。"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.services.model_gateway.providers.base import LLMProvider
from app.services.model_gateway.types import (
    LLMChatResult,
    LLMChatSpec,
    ProviderError,
    ProviderTimeout,
)

logger = logging.getLogger(__name__)


class OpenAICompatLLM(LLMProvider):
    """通用 OpenAI Chat Completions 兼容客户端。"""

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        default_model: str,
        timeout_sec: float = 60.0,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_model = default_model
        self._timeout_sec = timeout_sec

    def chat(self, spec: LLMChatSpec) -> LLMChatResult:
        if not self._api_key:
            raise ProviderError(f"{self.name}: api_key 未配置")

        import requests

        model = spec.model_hint or self._default_model
        messages: list[dict[str, str]] = []
        if spec.system:
            messages.append({"role": "system", "content": spec.system})
        messages.append({"role": "user", "content": spec.user})

        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": spec.temperature,
        }
        if spec.max_tokens:
            payload["max_tokens"] = spec.max_tokens
        if spec.response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_sec,
            )
        except requests.Timeout as exc:
            raise ProviderTimeout(f"{self.name}: timeout") from exc
        except requests.RequestException as exc:
            raise ProviderError(f"{self.name}: request failed: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            text_excerpt = (resp.text or "")[:300]
            raise ProviderError(
                f"{self.name}: HTTP {resp.status_code}: {text_excerpt}"
            )

        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"{self.name}: 响应解析失败: {exc}") from exc

        usage = (body or {}).get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)

        return LLMChatResult(
            text=text,
            provider=self.name,
            model=model,
            duration_ms=elapsed_ms,
            cost_usd=0.0,  # 由 gateway 估算补齐
            raw={
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        )

    @staticmethod
    def usage_tokens(result: LLMChatResult) -> tuple[int, int]:
        usage: Optional[dict] = (result.raw or {}).get("usage")
        if not usage:
            return 0, 0
        return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
