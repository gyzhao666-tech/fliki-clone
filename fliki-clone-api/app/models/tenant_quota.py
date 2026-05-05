"""配额 v2 模型：tenant 级月度配额 + provider 级并发分桶。

与 v1 的 `model_quotas` 区别
-------------------------
- v1 按 `user_id` 一行；v2 按 `tenant_id` 一行（命名空间 `ws:{workspace.id}` 或 `u:{user_id}` 兜底）。
- v2 引入 `plan`：reserve / concurrent_max / max_concurrent 默认值按 plan 派生。
- v2 新增 `provider_concurrency_buckets`：每 (tenant_id, provider_name) 一行，
  挡住「一个 tenant 把 SiliconFlow 把所有并发槽吃光」的尾部场景。

并发模型
-------
- `tenant_quotas`：reserve / release 走 `SELECT ... FOR UPDATE`（PG）。
- `provider_concurrency_buckets`：`acquire` 走 `UPDATE ... WHERE current_in_flight < max_concurrent`，
  影响 0 行视为获取失败；`release` 用 `GREATEST(current_in_flight - 1, 0)` 兜底。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TenantQuota(Base):
    """tenant 级配额；每个 tenant_id 唯一。

    `tenant_id` 命名空间约定（见 `app/services/pipeline/tenant.py::resolve_tenant_id`）：
    - `ws:{workspace.id}` —— user 拥有的第一个 workspace 命中
    - `u:{user_id}` —— user 没绑 workspace 的兜底
    """

    __tablename__ = "tenant_quotas"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="free")

    monthly_limit_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )
    current_period_usage_usd: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    concurrent_max: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"TenantQuota(tenant_id={self.tenant_id!r}, plan={self.plan!r}, "
            f"used={self.current_period_usage_usd:.4f}/{self.monthly_limit_usd:.2f})"
        )


class ProviderConcurrencyBucket(Base):
    """tenant × provider 的并发槽位。

    业务侧不直接读这张表；通过 `provider_buckets.acquire/release` 维护。
    """

    __tablename__ = "provider_concurrency_buckets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_name", name="uq_provider_bucket_tenant_provider"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider_name: Mapped[str] = mapped_column(String(50), nullable=False)

    current_in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_concurrent: Mapped[int] = mapped_column(Integer, nullable=False, default=4)

    last_acquired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["TenantQuota", "ProviderConcurrencyBucket"]
