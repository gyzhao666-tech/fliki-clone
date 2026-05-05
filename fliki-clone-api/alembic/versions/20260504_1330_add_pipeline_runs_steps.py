"""add_pipeline_runs_steps

Revision ID: 9a6e4d127b58
Revises: 7f51c2a48e10
Create Date: 2026-05-04 13:30:00.000000+00:00

新增 pipeline_runs / pipeline_steps，作为 Agent 流水线的执行根记录与节点。
对应 ADR-001 与 services/pipeline 模块。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9a6e4d127b58"
down_revision: Union[str, None] = "7f51c2a48e10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "file_id",
            sa.String(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("template_name", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("graph_json", sa.JSON(), nullable=True),
        sa.Column("inputs_json", sa.JSON(), nullable=True),
        sa.Column("outputs_json", sa.JSON(), nullable=True),
        sa.Column("cost_estimated_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_actual_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_runs_file_id", "pipeline_runs", ["file_id"])
    op.create_index("ix_pipeline_runs_user_id", "pipeline_runs", ["user_id"])
    op.create_index("ix_pipeline_runs_state", "pipeline_runs", ["state"])

    op.create_table(
        "pipeline_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("agent_type", sa.String(length=40), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requires_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inputs_json", sa.JSON(), nullable=True),
        sa.Column("outputs_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipeline_steps_run_id", "pipeline_steps", ["run_id"])
    op.create_index("ix_pipeline_steps_agent_type", "pipeline_steps", ["agent_type"])
    op.create_index("ix_pipeline_steps_state", "pipeline_steps", ["state"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_steps_state", table_name="pipeline_steps")
    op.drop_index("ix_pipeline_steps_agent_type", table_name="pipeline_steps")
    op.drop_index("ix_pipeline_steps_run_id", table_name="pipeline_steps")
    op.drop_table("pipeline_steps")
    op.drop_index("ix_pipeline_runs_state", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_user_id", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_file_id", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
