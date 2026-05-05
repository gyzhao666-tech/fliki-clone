"""Dead-letter task table（worker 异常 / 重试耗尽后的兜底持久化）。

设计要点
-------
- 仅记录无法被业务逻辑（`StepResult.FAILED`）翻译的异常：worker SIGKILL / OOM /
  序列化错 / DB 连接异常 / `task_acks_late=True + task_reject_on_worker_lost=True` 下的
  worker_lost 重发耗尽
- 关联 run_id / step_id 便于 user 在前端按 run 查死信
- args / kwargs 按 JSON 持久化，便于 retry 时反序列化重投
- status：`pending` 默认 / `retried`（已被人手动重投）/ `discarded`（user 主动丢弃）

不在这里存的：
- 业务级 step 失败（`pipeline_steps.state='failed' + error`）—— 那是正常状态机
- 配额拦截 / 校验异常（直接 HTTP 4xx）
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


DLQ_STATUSES = ("pending", "retried", "discarded")


class DeadLetterTask(Base):
    __tablename__ = "dead_letter_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # 来源标识：celery task name 或者 'background.tick' / 'background.execute_step'
    task_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    args_json: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    kwargs_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    # 关联 run / step（cascade SET NULL：run/step 被删时 DLQ 项保留以便审计）
    run_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_runs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    step_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("pipeline_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    # 错误信息
    error: Mapped[str] = mapped_column(Text, nullable=False)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 同一逻辑任务（同 args + 同 task_name）失败累计次数；retry 后清零并标 retried
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    first_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    last_failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


__all__ = ["DeadLetterTask", "DLQ_STATUSES"]
