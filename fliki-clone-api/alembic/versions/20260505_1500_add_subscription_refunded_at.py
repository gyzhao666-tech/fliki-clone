"""add_subscription_refunded_at

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-05 15:00:00.000000+00:00

Track-16 · Stripe webhook 退款事件
==================================

加 `subscriptions.refunded_at: TIMESTAMP NULL`，用于记录 stripe `charge.refunded`
事件落到本订阅的时刻。**不会**自动回滚 `tenant_quotas`：

- 退款发生在月中，但已用配额可能已经产生真实成本（已付给 OpenAI / SiliconFlow 的钱
  追不回来）；强制把月度 limit / concurrent_max 立即清零会让用户当月已起的 run
  突然挂掉，体验差
- v1 的策略：只打标 → ops 人工评估退款原因 → 必要时手动跑 `update_tenant_plan`
  降级（保留 monthly_limit_usd 当月不变）
- L-04 follow-up：跨月 cron 自动把 refunded_at < period_start 的订阅 plan 强制 free

为什么 nullable：
- 绝大多数 active subscription 没退款；列默认 NULL 占空间最少
- `refunded_at IS NOT NULL` 自然就是「已退款」过滤条件
- 不加 server_default NOW()，避免老行误打标

不加索引：
- 退款查询频次极低（人手 ops 触发）
- subscriptions 表行数小（每个用户 1-N 行），seq scan 即可
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "refunded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "refunded_at")
