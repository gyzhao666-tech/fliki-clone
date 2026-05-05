"""add_template_config_json

Revision ID: 2b9f1c0d4a73
Revises: 8e2f4d7a6c91
Create Date: 2026-04-26 11:28:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "2b9f1c0d4a73"
down_revision: Union[str, None] = "8e2f4d7a6c91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("templates", "config_json")
