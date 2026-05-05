"""发布平台 adapter 注册中心。

每个 adapter 通过 `register_adapter("platform_name")(cls)` 装饰器注册。
模块顶层 import 触发注册（与 pipeline.agents 同模式）。

`get_adapter("youtube") -> PlatformAdapter` 返回实例。未知平台返 dry-run。
"""
from __future__ import annotations

from .base import (
    PlatformAdapter,
    PublishError,
    PublishOutcome,
    PublishRequest,
    get_adapter,
    list_supported_platforms,
    register_adapter,
)

# 触发各 adapter 的 register 装饰器执行（顺序无关）
from . import bilibili as _bilibili  # noqa: F401
from . import dry_run as _dry_run  # noqa: F401
from . import youtube as _youtube  # noqa: F401


__all__ = [
    "PlatformAdapter",
    "PublishError",
    "PublishOutcome",
    "PublishRequest",
    "get_adapter",
    "list_supported_platforms",
    "register_adapter",
]
