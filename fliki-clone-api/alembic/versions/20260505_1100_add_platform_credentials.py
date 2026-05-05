"""add_platform_credentials

Revision ID: 8b1f6c2d4a93
Revises: c2f9b7a04ef1
Create Date: 2026-05-05 11:00:00.000000+00:00

发布执行器 v1：每个 user × platform 一行存 OAuth 凭证（access/refresh token + 过期时间）。

设计要点
-------
- 不引入 PG ENUM；platform 用 string（"youtube" / "bilibili" / "twitter" / ...），便于扩展
- access_token / refresh_token 直接存 text；生产环境应在 app 层用 Fernet 之类对称加密再写库；
  v1 先明文存（与现有 .env 里的 plain key 风格一致），TODO 标在 service 层
- (user_id, platform) 唯一：同一 user 同一平台只允许 1 套有效凭证
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8b1f6c2d4a93"
down_revision: Union[str, None] = "c2f9b7a04ef1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("external_user_id", sa.String(120), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope_json", sa.JSON(), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
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
        "uq_platform_credentials_user_platform",
        "platform_credentials",
        ["user_id", "platform"],
    )
    op.create_index(
        "ix_platform_credentials_user_id", "platform_credentials", ["user_id"]
    )
    op.create_index(
        "ix_platform_credentials_platform", "platform_credentials", ["platform"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_credentials_platform", table_name="platform_credentials"
    )
    op.drop_index(
        "ix_platform_credentials_user_id", table_name="platform_credentials"
    )
    op.drop_constraint(
        "uq_platform_credentials_user_platform",
        "platform_credentials",
        type_="unique",
    )
    op.drop_table("platform_credentials")
