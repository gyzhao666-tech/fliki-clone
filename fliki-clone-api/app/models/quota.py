"""模型调用配额（user 级，按月计费周期）。

目标：
- 在启动 pipeline 前预扣预估成本，防止单次 run 把月度配额烧光
- 在 run 终态时把「预扣 - 实际」的差退回，避免长期累计偏差
- 提供 `concurrent_max`，未来用于限制同时运行的 pipeline 数（v1 不强制）

设计取舍：
- 现在只按 `user_id` 一行；后续要扩 tenant 时再加 `tenant_id`
- `current_period_start` 写当前自然月的第一天 UTC；按月手动 / 自动 rollover
- `current_period_usage_usd` 含「已实际花费 + 当前未结算的预扣」
- `monthly_limit_usd` 默认 10 USD；plan 升级时通过其它流程改写
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelQuota(Base):
    """user 级配额条目；每个 user_id 唯一。"""

    __tablename__ = "model_quotas"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    monthly_limit_usd: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
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
            f"ModelQuota(user_id={self.user_id!r}, "
            f"used={self.current_period_usage_usd:.4f}/{self.monthly_limit_usd:.2f})"
        )
