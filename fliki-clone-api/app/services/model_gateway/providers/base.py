"""Provider 抽象基类。

每个 provider 只关心“怎么把统一的 RenderRequest 翻译成自家 API 调用”，
不负责记账、限流、重试、降级 —— 这些由 gateway 统一处理。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import ModelAction, ProviderName, RenderRequest, RenderResult


class BaseProvider(ABC):
    """所有 provider 共有的接口。"""

    name: ProviderName

    @abstractmethod
    def supports(self, action: ModelAction) -> bool:
        """是否支持指定动作。"""

    @abstractmethod
    def is_available(self) -> bool:
        """配置是否完整、是否可用。无 API key 时应返回 False。"""

    @abstractmethod
    def call(self, request: RenderRequest) -> RenderResult:
        """执行调用。允许抛异常；gateway 会捕获并转换成 FAILED。"""
