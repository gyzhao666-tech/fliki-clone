"""add_tenant_quota_and_provider_buckets

Revision ID: c2f9b7a04ef1
Revises: e58c4a1d2b73
Create Date: 2026-05-05 09:00:00.000000+00:00

配额 v2：tenant 级分桶 + provider 级并发分桶 + pipeline_runs.tenant_id 列。

设计要点
-------
1. 不删除 `model_quotas`：v1 user 级配额作为兼容期数据源继续存在；
   v2 tenant 级 reserve 完全独立写 `tenant_quotas`，迁移期可双轨。
2. tenant_id 命名空间：`ws:{workspace.id}` 优先；user 没绑 workspace 时 `u:{user_id}`。
3. provider 并发分桶按 (tenant_id, provider_name) 唯一；max_concurrent 默认按 plan + provider 派生。
4. 一次性 backfill：把 pipeline_runs 现有行的 tenant_id 填成 `u:{user_id}`，避免历史 run 在 v2 视图里全是空。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c2f9b7a04ef1"
down_revision: Union[str, None] = "e58c4a1d2b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. tenant_quotas ──────────────────────────────────────────────────
    op.create_table(
        "tenant_quotas",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("monthly_limit_usd", sa.Float(), nullable=False, server_default="10.0"),
        sa.Column(
            "current_period_usage_usd",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "current_period_start",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("concurrent_max", sa.Integer(), nullable=False, server_default="2"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_tenant_quotas_plan", "tenant_quotas", ["plan"])

    # ── 2. provider_concurrency_buckets ───────────────────────────────────
    op.create_table(
        "provider_concurrency_buckets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("provider_name", sa.String(50), nullable=False),
        sa.Column(
            "current_in_flight",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("max_concurrent", sa.Integer(), nullable=False, server_default="4"),
        sa.Column(
            "last_acquired_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_released_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_provider_bucket_tenant_provider",
        "provider_concurrency_buckets",
        ["tenant_id", "provider_name"],
    )
    op.create_index(
        "ix_provider_bucket_tenant", "provider_concurrency_buckets", ["tenant_id"]
    )

    # ── 3. pipeline_runs.tenant_id ────────────────────────────────────────
    op.add_column(
        "pipeline_runs",
        sa.Column("tenant_id", sa.String(), nullable=True),
    )
    op.create_index("ix_pipeline_runs_tenant_id", "pipeline_runs", ["tenant_id"])

    # ── 4. backfill：旧 run 的 tenant_id 填 u:{user_id} ───────────────────
    # PG 才能跑这条；SQLite 也兼容
    op.execute(
        """
        UPDATE pipeline_runs
           SET tenant_id = 'u:' || user_id
         WHERE tenant_id IS NULL AND user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_tenant_id", table_name="pipeline_runs")
    op.drop_column("pipeline_runs", "tenant_id")

    op.drop_index(
        "ix_provider_bucket_tenant", table_name="provider_concurrency_buckets"
    )
    op.drop_constraint(
        "uq_provider_bucket_tenant_provider",
        "provider_concurrency_buckets",
        type_="unique",
    )
    op.drop_table("provider_concurrency_buckets")

    op.drop_index("ix_tenant_quotas_plan", table_name="tenant_quotas")
    op.drop_table("tenant_quotas")
