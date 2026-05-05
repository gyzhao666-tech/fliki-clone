"""add_file_project_fields

Revision ID: 4c8d1e6b9a20
Revises: b313cffa372b
Create Date: 2026-04-26 09:07:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4c8d1e6b9a20"
down_revision: Union[str, None] = "b313cffa372b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("files", sa.Column("project_type", sa.String(length=50), nullable=False, server_default="story_video"))
    op.add_column("files", sa.Column("product_name", sa.String(length=255), nullable=True))
    op.add_column("files", sa.Column("target_market", sa.String(length=100), nullable=True))
    op.add_column("files", sa.Column("selling_points_json", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("brand_terms", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("avoid_terms", sa.Text(), nullable=True))
    op.add_column("files", sa.Column("aspect_ratio", sa.String(length=20), nullable=False, server_default="16:9"))
    op.add_column("files", sa.Column("copyright_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("files", "copyright_confirmed")
    op.drop_column("files", "aspect_ratio")
    op.drop_column("files", "avoid_terms")
    op.drop_column("files", "brand_terms")
    op.drop_column("files", "selling_points_json")
    op.drop_column("files", "target_market")
    op.drop_column("files", "product_name")
    op.drop_column("files", "project_type")
