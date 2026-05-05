"""add_model_calls

Revision ID: 7f51c2a48e10
Revises: 2b9f1c0d4a73
Create Date: 2026-05-04 13:00:00.000000+00:00

新增 model_calls 表，作为所有外部模型调用的统一账单与可观测性来源。
对应 ADR-001 与 services/model_gateway 模块。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "7f51c2a48e10"
down_revision: Union[str, None] = "2b9f1c0d4a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("file_id", sa.String(), nullable=True),
        sa.Column("pipeline_step_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("request_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_model_calls_user_id", "model_calls", ["user_id"])
    op.create_index("ix_model_calls_file_id", "model_calls", ["file_id"])
    op.create_index("ix_model_calls_pipeline_step_id", "model_calls", ["pipeline_step_id"])
    op.create_index("ix_model_calls_provider", "model_calls", ["provider"])
    op.create_index("ix_model_calls_action", "model_calls", ["action"])
    op.create_index("ix_model_calls_created_at", "model_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_calls_created_at", table_name="model_calls")
    op.drop_index("ix_model_calls_action", table_name="model_calls")
    op.drop_index("ix_model_calls_provider", table_name="model_calls")
    op.drop_index("ix_model_calls_pipeline_step_id", table_name="model_calls")
    op.drop_index("ix_model_calls_file_id", table_name="model_calls")
    op.drop_index("ix_model_calls_user_id", table_name="model_calls")
    op.drop_table("model_calls")
