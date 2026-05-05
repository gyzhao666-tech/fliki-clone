"""add_scene_planning_fields

Revision ID: 8e2f4d7a6c91
Revises: 4c8d1e6b9a20
Create Date: 2026-04-26 09:12:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8e2f4d7a6c91"
down_revision: Union[str, None] = "4c8d1e6b9a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("scene_goal", sa.String(length=100), nullable=True))
    op.add_column("scenes", sa.Column("selling_point", sa.String(length=1024), nullable=True))
    op.add_column("scenes", sa.Column("asset_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_scenes_asset_id_assets",
        "scenes",
        "assets",
        ["asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_scenes_asset_id_assets", "scenes", type_="foreignkey")
    op.drop_column("scenes", "asset_id")
    op.drop_column("scenes", "selling_point")
    op.drop_column("scenes", "scene_goal")
