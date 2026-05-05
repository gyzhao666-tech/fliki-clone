"""灰度发布 feature flag 模型（Track-10）。

按 (tenant_id, flag_name) 维度存任意 JSON value。语义不在 ORM 这一层定义；
agent / 路由层各自约定自己的 flag 名 + value 形态：

- `art_ipadapter_pct`     → `{"pct": 0..100}` 主角镜走 v4 IP-Adapter 的比例；
                            其余镜降到 v3 prompt-only
- `voice_word_align_v4`   → `{"enabled": true/false}` 是否走 word-level 强对齐
- `<agent>_variant`       → `{"variant": "v3"/"v4"/"vN"}` 任意版本切换

写库走 services/pipeline/feature_flags.py，避免业务侧直接拼 SQL；
唯一约束保证「同 tenant 同 flag 只一行」语义在 DB 层兜底。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FeatureFlag(Base):
    """tenant × flag_name 一行；value 任意 JSON。"""

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "flag_name", name="uq_feature_flags_tenant_flag"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    flag_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"FeatureFlag(tenant_id={self.tenant_id!r}, "
            f"flag={self.flag_name!r}, value={self.value_json!r})"
        )


__all__ = ["FeatureFlag"]
