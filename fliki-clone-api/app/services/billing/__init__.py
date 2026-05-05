"""Stripe 计费对接（Track-11）。

模块结构
-------
- `stripe_client.py`：包 `stripe` SDK 的薄封装。负责
  - `init_stripe()`：按 settings.stripe_secret_key 设置 SDK 全局；缺 key 时抛
    `StripeNotConfigured`，让 router 给前端清晰错误而不是 500
  - `create_checkout_session()` / `create_portal_session()` / `verify_webhook_event()`
  - `plan_for_price_id(price_id)`：把 stripe price_id 反查成内部 plan 名
- `webhook_handlers.py`：处理 stripe webhook 各事件
  - checkout.session.completed → upsert subscriptions 行 + user.plan + tenant 同步
  - customer.subscription.updated → plan/status/period_end 跟随 stripe 变
  - customer.subscription.deleted → status=canceled + 降回 free + 重新同步 tenant
  - invoice.payment_failed → status=past_due
- `tenant_sync.py`：把 user 维度的 plan 切换映射到 v2 tenant 维度的 plan + 配额 bump
  调链：`sync_user_plan(user_id, new_plan)` → 解析 tenant_id（同 pipeline.tenant 模块）
  → 调 `quota.update_tenant_plan(tenant_id, new_plan)`（升级 bump、降级保留）

设计取舍
-------
- 不在 webhook 里直接动 SDK 调用 stripe，避免 stripe 端临时不可达把签名验证后的事件丢弃
- 写 DB 用同步 sync engine（与 quota / runner 一致）；router 是 async 但 webhook
  body 已读取，handler 内部走 sync 是 OK 的（短查询，全部 < 50ms）
- subscriptions 表已有 v1 schema（user_id / stripe_sub_id / stripe_customer_id /
  plan / status / current_period_end）；本 Track 不动 schema
- 失败语义：handler 抛异常 → router catch + 返 200（stripe 重试机制）+ 写日志，
  避免 stripe 不停重发把 worker 打满；DB 落库失败用结构化日志便于人手对账
"""
from __future__ import annotations

from .stripe_client import (
    StripeNotConfigured,
    create_checkout_session,
    create_portal_session,
    init_stripe,
    plan_for_price_id,
    verify_webhook_event,
)
from .tenant_sync import sync_user_plan
from .webhook_handlers import handle_webhook_event

__all__ = [
    "StripeNotConfigured",
    "create_checkout_session",
    "create_portal_session",
    "handle_webhook_event",
    "init_stripe",
    "plan_for_price_id",
    "sync_user_plan",
    "verify_webhook_event",
]
