import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ModelCall(Base):
    """所有外部模型调用的统一账单 / 可观测性记录。

    - 每次 gateway.run(...) 都会写一条
    - 不与具体业务表强外键耦合（user_id / file_id / pipeline_step_id 都用 nullable）
    - 后续可基于此表做：成本面板、配额拦截、provider 健康度统计
    """

    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    file_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    pipeline_step_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    error: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    request_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
