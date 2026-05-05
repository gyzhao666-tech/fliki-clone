"""薄封装 stripe SDK，把所有「读 settings + 调 stripe」的胶水集中在这。

这一层故意不碰 DB / 不碰 tenant_quotas，只做 stripe 边界翻译：
- create_checkout_session：拿 user + plan → stripe Checkout Session
- create_portal_session：拿 customer_id → stripe Billing Portal Session
- verify_webhook_event：原始 body + 签名 → 已验签的 stripe.Event
- plan_for_price_id：反查 internal plan 名（free / standard / premium）

router 层和 webhook_handlers 层都只调本模块，互不感知 stripe 内部对象结构变化。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import stripe

from app.config import get_settings

logger = logging.getLogger(__name__)


class StripeNotConfigured(RuntimeError):
    """settings.stripe_secret_key 为空时抛；router 翻译成 503。"""


_INITIALIZED = False


def init_stripe() -> None:
    """把 SDK 全局 api_key 设上；幂等。

    注意：stripe SDK 用的是模块级 `stripe.api_key`，所以多 worker / 多进程都各自调一次即可。
    缺 key 时抛 StripeNotConfigured，避免后续 stripe.* 调用拿到 None key 401。
    """
    global _INITIALIZED
    settings = get_settings()
    key = settings.stripe_secret_key.strip()
    if not key or key.startswith("sk_test_..."):  # 默认占位符也算未配置
        raise StripeNotConfigured(
            "STRIPE_SECRET_KEY 未配置；在 .env 设置真实 sk_test_/sk_live_ key 后重启 backend"
        )
    if not _INITIALIZED or stripe.api_key != key:
        stripe.api_key = key
        _INITIALIZED = True


def _price_to_plan_map() -> dict[str, str]:
    """从 settings 反推 price_id → plan 名映射；只包含已配置的档位。"""
    settings = get_settings()
    out: dict[str, str] = {}
    for plan, price in (
        ("free", getattr(settings, "stripe_price_free", "")),
        ("standard", settings.stripe_price_standard),
        ("premium", settings.stripe_price_premium),
    ):
        if price and not price.startswith("price_..."):
            out[price] = plan
    return out


def _plan_to_price_map() -> dict[str, str]:
    settings = get_settings()
    out: dict[str, str] = {}
    for plan, price in (
        ("free", getattr(settings, "stripe_price_free", "")),
        ("standard", settings.stripe_price_standard),
        ("premium", settings.stripe_price_premium),
    ):
        if price and not price.startswith("price_..."):
            out[plan] = price
    return out


def plan_for_price_id(price_id: Optional[str]) -> Optional[str]:
    """webhook 里 line_item / subscription.items 给的是 stripe price id，
    本函数反查回内部 plan 名（free/standard/premium）。未知 price 返 None，
    让 caller 决定降级（通常视为 standard）。
    """
    if not price_id:
        return None
    return _price_to_plan_map().get(price_id)


def create_checkout_session(
    *,
    plan: str,
    user_id: str,
    user_email: Optional[str],
    success_url: str,
    cancel_url: str,
    customer_id: Optional[str] = None,
) -> dict[str, Any]:
    """创建 Stripe Checkout Session，返回 `{id, url}`。

    plan 必须在已配置的 `_plan_to_price_map()` 里；否则抛 ValueError，
    router 翻译成 400 而不是把空 price_id 提给 stripe。

    metadata 带 user_id + plan，webhook 里就能反查到「是哪个用户买的什么档」。
    customer_email 仅在没现存 customer_id 时传，避免 stripe 弹 "customer already exists"。
    """
    init_stripe()

    price_map = _plan_to_price_map()
    price_id = price_map.get(plan)
    if not price_id:
        raise ValueError(
            f"unknown or unconfigured plan: {plan!r}; "
            f"configured plans: {sorted(price_map.keys())}"
        )

    kwargs: dict[str, Any] = dict(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=(
            success_url + ("&" if "?" in success_url else "?") + "session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url=cancel_url,
        metadata={"user_id": user_id, "plan": plan},
        subscription_data={"metadata": {"user_id": user_id, "plan": plan}},
        client_reference_id=user_id,
    )
    if customer_id:
        kwargs["customer"] = customer_id
    elif user_email:
        kwargs["customer_email"] = user_email

    session = stripe.checkout.Session.create(**kwargs)
    return {"id": session.id, "url": session.url}


def create_portal_session(*, customer_id: str, return_url: str) -> dict[str, Any]:
    """开 Stripe Customer Portal session（升级 / 降级 / 退订全交给 stripe 托管 UI）。"""
    init_stripe()
    if not customer_id:
        raise ValueError("customer_id required")
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return {"id": session.id, "url": session.url}


def verify_webhook_event(payload: bytes, signature: Optional[str]) -> stripe.Event:
    """用 webhook secret 验签；签名错抛 stripe.error.SignatureVerificationError；
    secret 未配置抛 StripeNotConfigured（router 翻译成 503，避免静默接收非法 webhook）。
    """
    settings = get_settings()
    secret = settings.stripe_webhook_secret.strip()
    if not secret or secret.startswith("whsec_..."):
        raise StripeNotConfigured(
            "STRIPE_WEBHOOK_SECRET 未配置；本地开发可用 `stripe listen --print-secret`"
        )
    init_stripe()
    return stripe.Webhook.construct_event(payload, signature or "", secret)
