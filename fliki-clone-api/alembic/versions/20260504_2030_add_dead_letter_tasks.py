"""add_dead_letter_tasks

Revision ID: e58c4a1d2b73
Revises: a4d72b91e3c5
Create Date: 2026-05-04 20:30:00.000000+00:00

新表 `dead_letter_tasks`：worker 异常 / 重试耗尽后的兜底持久化。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e58c4a1d2b73"
down_revision: Union[str, None] = "a4d72b91e3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dead_letter_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_name", sa.String(120), nullable=False),
        sa.Column("args_json", sa.JSON(), nullable=True),
        sa.Column("kwargs_json", sa.JSON(), nullable=True),
        sa.Column("run_id", sa.String(),
                  sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_id", sa.String(),
                  sa.ForeignKey("pipeline_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_failed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dlq_task_name", "dead_letter_tasks", ["task_name"])
    op.create_index("ix_dlq_run_id", "dead_letter_tasks", ["run_id"])
    op.create_index("ix_dlq_user_id", "dead_letter_tasks", ["user_id"])
    op.create_index("ix_dlq_status", "dead_letter_tasks", ["status"])
    # 复合索引便于「按 user 列 pending」最常见查询
    op.create_index(
        "ix_dlq_user_status_created",
        "dead_letter_tasks",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dlq_user_status_created", table_name="dead_letter_tasks")
    op.drop_index("ix_dlq_status", table_name="dead_letter_tasks")
    op.drop_index("ix_dlq_user_id", table_name="dead_letter_tasks")
    op.drop_index("ix_dlq_run_id", table_name="dead_letter_tasks")
    op.drop_index("ix_dlq_task_name", table_name="dead_letter_tasks")
    op.drop_table("dead_letter_tasks")
