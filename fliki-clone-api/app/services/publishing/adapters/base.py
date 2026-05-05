"""发布平台 adapter 协议。

每个平台实现一个 `PlatformAdapter` 子类（或符合 Protocol 的 callable），
通过 `register_adapter("name")(cls)` 装饰器注册到全局表。

执行器入口：`adapter.upload(req) -> PublishOutcome`。
- 业务级失败（auth 缺失 / 平台拒收 / metadata 不合法）：返 PublishOutcome(ok=False, error=...)
- 系统级异常（网络断 / 5xx）：抛 PublishError，让 executor 翻成 DLQ 入库
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional, Type


@dataclass
class PublishRequest:
    """提交给 adapter 的所有上下文（DB 已读出来的扁平视图）。"""

    plan_id: str
    user_id: str
    platform: str
    file_id: str
    run_id: Optional[str]
    render_id: Optional[str]
    render_url: Optional[str]
    cover_url: Optional[str]
    title: Optional[str]
    description: Optional[str]
    tags: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    aspect_ratio: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    # OAuth 凭证：access_token / refresh_token / scope_json
    credential: Optional[dict[str, Any]] = None
    # 调用方可注入 idempotency_key 防重复发布
    idempotency_key: Optional[str] = None
    # 安全闸门：默认 False = adapter 走 mock / dry-run；True = adapter 真打外部 API
    # （Track-02：替代 v1 的 plan.meta_json.confirm_real_publish 隐藏字段）
    confirm_real_publish: bool = False


@dataclass
class PublishOutcome:
    """adapter 返给 executor 的结果。"""

    ok: bool
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    status: str = "published"  # published / scheduled / failed
    published_at: Optional[datetime] = None
    error: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)
    # adapter 决定要不要把更新后的 token 写回 credential 表
    credential_update: Optional[dict[str, Any]] = None


class PublishError(Exception):
    """系统级异常：网络中断 / 平台 5xx / 凭证刷新失败。executor 把它入 DLQ。"""


class PlatformAdapter:
    """所有平台 adapter 的基类。最小协议：

    - `name`：与 publish_plans.platform 列匹配
    - `is_real`：是否真发；False 表示 dry-run / stub
    - `requires_credential`：是否需要 OAuth 凭证
    - `upload(req) -> PublishOutcome`：上传主入口
    """

    name: str = "base"
    is_real: bool = False
    requires_credential: bool = False

    def upload(self, req: PublishRequest) -> PublishOutcome:  # pragma: no cover - abstract
        raise NotImplementedError


# ── 注册表 ───────────────────────────────────────────────────────────────────
_REGISTRY: dict[str, Type[PlatformAdapter]] = {}


def register_adapter(
    name: str,
) -> Callable[[Type[PlatformAdapter]], Type[PlatformAdapter]]:
    def deco(cls: Type[PlatformAdapter]) -> Type[PlatformAdapter]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def get_adapter(platform: str) -> PlatformAdapter:
    """返 adapter 实例。未知平台返 dry-run（让 executor 给个温和 fallback）。"""
    cls = _REGISTRY.get(platform)
    if cls is None:
        cls = _REGISTRY.get("dry-run")
        if cls is None:  # pragma: no cover - dry-run 永远应被注册
            raise PublishError(f"no adapter registered, even dry-run missing")
    return cls()


def list_supported_platforms() -> list[dict[str, Any]]:
    """前端「绑定平台」面板用。"""
    out: list[dict[str, Any]] = []
    for name, cls in sorted(_REGISTRY.items()):
        instance = cls()
        out.append(
            {
                "name": name,
                "is_real": bool(getattr(instance, "is_real", False)),
                "requires_credential": bool(
                    getattr(instance, "requires_credential", False)
                ),
            }
        )
    return out


__all__ = [
    "PlatformAdapter",
    "PublishError",
    "PublishOutcome",
    "PublishRequest",
    "get_adapter",
    "list_supported_platforms",
    "register_adapter",
]
