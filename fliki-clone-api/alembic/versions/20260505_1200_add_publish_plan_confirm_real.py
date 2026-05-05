"""add_publish_plan_confirm_real

Revision ID: 9c2d4e5f6a7b
Revises: 8b1f6c2d4a93
Create Date: 2026-05-05 12:00:00.000000+00:00

Track-02 · YouTube 真发安全闸门：把 v1 隐藏在 `meta_json.confirm_real_publish` 的开关
提到独立列，便于：
- 前端给 PlanRow 加 toggle 时不再去碰 meta_json 的 free-form JSON
- 后端 adapter 可以直接从 plan 行里读，不再依赖 executor 把 meta 拼到 credential 里
- 后续策略（per-tenant 默认 / 审计）可以围绕该列建索引

字段：`publish_plans.confirm_real_publish` BOOLEAN NOT NULL DEFAULT false。
默认 false 与现有「不真发」语义一致；旧行 backfill 自动取默认值，无需手工 UPDATE。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9c2d4e5f6a7b"
down_revision: Union[str, None] = "8b1f6c2d4a93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "publish_plans",
        sa.Column(
            "confirm_real_publish",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("publish_plans", "confirm_real_publish")
