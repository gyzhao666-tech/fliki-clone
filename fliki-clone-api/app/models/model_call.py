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
    # Track-18：配额 v2 的 tenant 命名空间（ws:{workspace_id} / u:{user_id} / anon:default）
    # 与 pipeline_runs.tenant_id 一致；老行通过 alembic c3d4e5f6a7b8 backfill 为 'u:{user_id}'。
    # gateway.record_call 优先写 request.tenant_id，缺失时按 user_id 兜底；让按 tenant
    # 聚合的 cost 查询不需要 join pipeline_runs 反推。
    tenant_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
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
