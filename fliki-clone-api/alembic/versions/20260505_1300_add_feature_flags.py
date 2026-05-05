"""add_feature_flags

Revision ID: a1b2c3d4e5f6
Revises: 9c2d4e5f6a7b
Create Date: 2026-05-05 13:00:00.000000+00:00

Track-10 · 灰度发布 / canary 路由
================================

新表 `feature_flags`（tenant_id × flag_name 维度），用来按 tenant 决定走哪个
agent 版本（v3 prompt-only / v4 IP-Adapter / 后续任意 X）。机制可复用到任意
agent 的版本切换：把 flag_name 起个稳定名字（如 `art_ipadapter_pct`），value 存
JSON（`{"pct": 50}` 或者 `{"variant": "v4"}`），由 agent 入口自行决定语义。

字段
----
- `tenant_id`：与 `tenant_quotas.tenant_id` 同口径（`ws:{wid}` / `u:{uid}` /
  `anon:default`）；不引外键，避免 anon 那一档没法落库
- `flag_name`：稳定 ASCII，例如 `art_ipadapter_pct` / `voice_word_align_v4`
- `value_json`：任意 JSON；典型值 `{"pct": 0..100}`、`{"enabled": true/false}`、
  `{"variant": "v4"}`
- 唯一约束 `(tenant_id, flag_name)`：每 tenant 同名 flag 只允许 1 行
- 普通索引 `flag_name`：admin 列表「这个 flag 现在开了多少 tenant」时用

为什么不直接塞 settings/env：
- 灰度需要按 tenant 染色，env 是全局的
- 后端 hot-reload 期间想动态调整 0%/50%/100%，env 必须重启进程
- 后续可以在 admin 面板里调；权限模型沿用 user.email in ALLOWED_ADMINS

为什么不放到 tenant_quotas.meta_json：
- meta_json 至今未引入，添加它会牵动 quota 模块语义
- 独立表更易做「这个 flag 现在影响多少 tenant」的聚合
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9c2d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("flag_name", sa.String(80), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
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
        "uq_feature_flags_tenant_flag",
        "feature_flags",
        ["tenant_id", "flag_name"],
    )
    op.create_index(
        "ix_feature_flags_tenant_id", "feature_flags", ["tenant_id"]
    )
    op.create_index(
        "ix_feature_flags_flag_name", "feature_flags", ["flag_name"]
    )


def downgrade() -> None:
    op.drop_index("ix_feature_flags_flag_name", table_name="feature_flags")
    op.drop_index("ix_feature_flags_tenant_id", table_name="feature_flags")
    op.drop_constraint(
        "uq_feature_flags_tenant_flag", "feature_flags", type_="unique"
    )
    op.drop_table("feature_flags")
