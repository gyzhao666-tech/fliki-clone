"""add_model_calls_tenant_id

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-05 16:00:00.000000+00:00

Track-18 · model_calls 加 tenant_id + 按 tenant 聚合
================================================

配额 v2 的 reserved_usd / actual_usd 是按 `tenant_quotas.tenant_id` 维度结算的，
但 `model_calls`（每次外部模型调用的明细账单）至今仍只挂 `user_id`：

- 跨 user 的 workspace（`ws:{workspace_id}` 命名空间）成本拆不开
- 多人协作的工作区按 user 分摊后只能看到「本人花了多少」，不知道「本工作区今天总
  烧了多少」
- 前端的 cost panel 想做「按 provider 拆分」时只能 join `pipeline_runs` 反推 tenant
  非常笨

本迁移：

1. 加 `model_calls.tenant_id VARCHAR NULL` 列
2. 加普通索引 `ix_model_calls_tenant_id`（聚合查询会按 tenant_id GROUP BY）
3. 一次性 backfill：

   ```sql
   UPDATE model_calls
      SET tenant_id = COALESCE('u:' || user_id, 'anon:default')
    WHERE tenant_id IS NULL
   ```

   - 老行的 user_id 可能为 NULL（dry-run / 后台任务），那种行落 `anon:default`
   - 与 `pipeline.tenant.resolve_tenant_id` 对老 user 的兜底逻辑一致

为什么 nullable：
- 旧行 backfill 后理论上都不为 NULL，但保持 nullable 让 record_call 失败兜底时
  能写一行没 tenant_id 的（不阻塞业务）
- gateway.record_call 之后会优先写 request.tenant_id；缺失时兜底 `u:{user_id}`
  或 `anon:default`

不加复合索引（`(tenant_id, created_at)` 或 `(tenant_id, provider)`）：
- v1 cost 查询频次不高（前端按需拉，不实时滚）
- 简单 idx + period_start range scan 已够用
- 复合 idx 写入开销更大，等真出现慢查询再加（DDL 不阻塞写）
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("tenant_id", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_model_calls_tenant_id",
        "model_calls",
        ["tenant_id"],
        unique=False,
    )
    # backfill：老行按 'u:{user_id}' 命名空间补齐；user_id 缺失走 anon:default
    op.execute(
        """
        UPDATE model_calls
           SET tenant_id = COALESCE('u:' || user_id, 'anon:default')
         WHERE tenant_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_model_calls_tenant_id", table_name="model_calls")
    op.drop_column("model_calls", "tenant_id")
