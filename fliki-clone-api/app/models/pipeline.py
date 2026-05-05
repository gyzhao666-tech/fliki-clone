"""Pipeline 运行与步骤模型。

- `PipelineRun`：一次完整流水线的执行（绑定一个 file_id / user_id）
- `PipelineStep`：DAG 中的一个节点（Agent 工位的执行）

设计原则：
- 状态字符串而非 Enum：方便 Alembic 与 PG 字符串字段对齐，前后端共享常量
- DAG 描述存 `graph_json`：节点定义 + 边；执行时从 `pipeline_steps` 实例化
- `attempt` 记录重试次数；单步重跑会 ++
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# ── 状态常量 ──────────────────────────────────────────────────────────────────
RUN_STATES = (
    "queued",
    "running",
    "awaiting_review",
    "partial_failed",
    "succeeded",
    "failed",
    "cancelled",
)

STEP_STATES = (
    "pending",
    "ready",
    "running",
    "awaiting_review",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
)


class PipelineRun(Base):
    """一次流水线运行的根记录。"""

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    file_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("files.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)

    graph_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    inputs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    outputs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    cost_estimated_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_actual_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # 启动时从 user 配额预扣的额度；终态结算后会把 (reserved - actual) 退回 quota
    cost_reserved_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PipelineStep(Base):
    """流水线中的单个节点。"""

    __tablename__ = "pipeline_steps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    depends_on_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_review: Mapped[bool] = mapped_column(
        # 用 Integer(0/1) 兼容 SQLite 测试，PG 走 0/1 也工作
        Integer, nullable=False, default=0
    )

    inputs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    outputs_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
