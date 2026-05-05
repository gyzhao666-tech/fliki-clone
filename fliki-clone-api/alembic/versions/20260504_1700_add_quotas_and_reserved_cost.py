"""add_quotas_and_reserved_cost

Revision ID: c1e8d3b2f0a9
Revises: 9a6e4d127b58
Create Date: 2026-05-04 17:00:00.000000+00:00

新增：
- `model_quotas` 表（user 级月度配额 + 并发上限 + 当前周期使用）
- `pipeline_runs.cost_reserved_usd` 字段（启动时从配额预扣的额度）

对应 services/pipeline/quota.py 与 cost.py。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c1e8d3b2f0a9"
down_revision: Union[str, None] = "9a6e4d127b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_quotas",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True),
        sa.Column("monthly_limit_usd", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column(
            "current_period_usage_usd", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "current_period_start",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("concurrent_max", sa.Integer(), nullable=False, server_default="2"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_model_quotas_user_id", "model_quotas", ["user_id"], unique=True)

    op.add_column(
        "pipeline_runs",
        sa.Column(
            "cost_reserved_usd", sa.Float(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "cost_reserved_usd")
    op.drop_index("ix_model_quotas_user_id", table_name="model_quotas")
    op.drop_table("model_quotas")
