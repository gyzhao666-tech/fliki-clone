"""平台 OAuth 凭证模型（发布执行器 v1）。

设计取舍
-------
- 字符串 enum：`platform` 用 string（"youtube" / "bilibili" / ...），不引入 PG ENUM；
  新增平台不需要 alembic
- (user_id, platform) 唯一约束：同 user 同 platform 只允许 1 套有效凭证；revoke 时把 row 删了
- access_token / refresh_token 字段层面是 plain text；生产环境应在 service 层用 Fernet
  对称加密；v1 与 .env 里的 plain key 风格一致，TODO 留在 publishing service 文档
- `status` 字段：`active` / `expired` / `revoked` / `error`
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


CREDENTIAL_STATUSES = ("active", "expired", "revoked", "error")


class PlatformCredential(Base):
    """user × platform 一行。"""

    __tablename__ = "platform_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform", name="uq_platform_credentials_user_platform"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    external_user_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scope_json: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    meta_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["PlatformCredential", "CREDENTIAL_STATUSES"]
