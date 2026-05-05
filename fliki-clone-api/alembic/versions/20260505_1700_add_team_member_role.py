"""add_team_member_role_default_index_backfill

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-05 17:00:00.000000+00:00

Track-24 · RBAC v1（workspace member role）
===========================================

把 Track-10/14/18/23 一直沿用的「邮箱白名单 admin」升级成基于
`team_members.role`（``admin`` / ``editor`` / ``viewer``）的 RBAC v1。

为什么本迁移看起来"很轻"
------------------------
``team_members.role`` 列在 ``initial_schema``（``875c67134df5``）里就已经存在
（``VARCHAR(20) NOT NULL``，无 server_default），但当时只是写死一个字段没有
任何业务消费。Track-24 第一次让它生效，因此本迁移的工作不是「加列」而是：

1. **加 server_default ``'editor'``**：之前列上没有 server default，应用层
   ORM 默认 ``default="editor"`` 仅在 Python 侧生效；alembic / 直接 SQL 插入
   仍要显式给 role。补 server default 让脚本插入 / 老业务 fallback 与 ORM 行为
   一致（pg ``ALTER COLUMN ... SET DEFAULT`` 是元数据操作，不锁表）。
2. **加普通索引 ``ix_team_members_role``**：``rbac.is_admin(workspace_id=None)``
   会走 ``WHERE user_id=:u AND role='admin'``；后续 admin metrics 视图也会
   按 role 聚合（"本 workspace 有几个 admin？"）。索引列基数虽然只 3 种，但
   配合 user_id 过滤后行数少，PG 仍会用。
3. **一次性 backfill：workspace owner → ``admin``**

   ```sql
   UPDATE team_members tm SET role='admin'
     FROM workspaces w
    WHERE tm.workspace_id = w.id AND tm.user_id = w.owner_id;
   ```

   语义：每个 workspace 的 owner（如果同时是 team_members 的一行）自动获得
   admin 角色；其余行保留原值（initial_schema 落库时 ORM 默认是 ``editor``，
   团队邀请生成的行也是 ``editor``）。

为什么 backfill 写在迁移里而不是 fixtures
----------------------------------------
- 迁移幂等：同样的 owner 已是 admin 时 UPDATE 是 noop（值相同），不会出错
- 老 user 已经在 prod 里建好的 workspace 也得到一致的 admin 角色，避免
  Track-24 上线后他们突然失去 admin 入口
- 写在迁移里有 down 路径：downgrade 把 role 全部清回 'editor'（不可逆 ←
  RBAC v1 的语义是「default editor」，admin 是 backfill 的特例，downgrade
  允许整体回退；具体见下方注释）

为什么 down 不删 role 列
------------------------
- role 列是 initial_schema 引入的，不是本 Track 加的；删列会破坏 base 结构
- downgrade 只回退本 Track 引入的「server_default + 索引 + backfill」三件事
- backfill 的逆操作并不能精确反推（无法区分「owner 本来就是 admin」与
  「owner 是被 backfill 上来的 admin」）；按 RBAC v1 简化语义，downgrade
  把所有 role 拉回 'editor'，让重新 upgrade 时 backfill 重新生效
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. server_default 'editor'：之前列存在但无 default
    op.alter_column(
        "team_members",
        "role",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default=sa.text("'editor'"),
    )

    # 2. 普通索引（rbac.is_admin 在 workspace_id 缺省时走 WHERE user_id=:u AND role='admin'）
    op.create_index(
        "ix_team_members_role",
        "team_members",
        ["role"],
        unique=False,
    )

    # 3. backfill：workspace owner 自动 admin（幂等：值相同则 noop）
    op.execute(
        """
        UPDATE team_members tm
           SET role = 'admin'
          FROM workspaces w
         WHERE tm.workspace_id = w.id
           AND tm.user_id = w.owner_id
           AND tm.role <> 'admin'
        """
    )


def downgrade() -> None:
    # 3' 反 backfill：本 Track 引入的「owner→admin」整体回退到 'editor'
    # 注：无法精确还原 backfill 之前每行的 role，按简化语义全部归一
    op.execute(
        """
        UPDATE team_members SET role = 'editor' WHERE role <> 'editor'
        """
    )

    # 2' 删索引
    op.drop_index("ix_team_members_role", table_name="team_members")

    # 1' 撤 server_default（恢复 initial_schema 行为）
    op.alter_column(
        "team_members",
        "role",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        server_default=None,
    )
