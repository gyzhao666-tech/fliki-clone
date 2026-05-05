"""Billing 路由（Track-11：Stripe 计费对接 + tenant_quotas v2 同步）。

端点
----
- GET  /billing/plan                  当前用户 plan + tenant 视图（usage / limit / concurrent）
- POST /billing/checkout-session      创建 stripe Checkout 链接，前端跳转
- POST /billing/portal-session        创建 Customer Portal 链接，前端跳转
- POST /billing/webhook               接 stripe webhook（verify signature → handler）

兼容旧端点（保留，避免前端 /settings/billing v1 mock UI 调 404）：
- POST /billing/checkout              （等价 /billing/checkout-session）
- POST /billing/portal                （等价 /billing/portal-session）

设计要点
-------
- 「升级即同步 tenant_quotas」由 webhook 完成；checkout-session 只创建支付链接，
  不直接动 user.plan（避免没付款就升级的 race）。
- webhook secret 缺失（dev / 测试）→ 503 + 清晰错误，避免静默接受非法请求。
- /billing/plan 同时返 tenant snapshot，让前端在不调 /pipelines/quota 的情况下
  也能展示真实的 monthly_limit_usd / concurrent_max（升级后立即可见）。
"""
from __future__ import annotations

import logging
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.billing import Subscription
from app.schemas import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
)
from app.services.billing import (
    StripeNotConfigured,
    create_checkout_session,
    create_portal_session,
    handle_webhook_event,
    verify_webhook_event,
)
from app.services.pipeline import tenant as pipeline_tenant
from app.services.pipeline.quota import get_or_create_tenant

logger = logging.getLogger(__name__)


router = APIRouter(tags=["Billing"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class TenantQuotaPreview(BaseModel):
    tenant_id: str
    tenant_plan: str
    monthly_limit_usd: float
    current_period_usage_usd: float
    concurrent_max: int


class BillingPlanV2Out(BaseModel):
    """`/billing/plan` 的响应：拼了 user / subscriptions / tenant_quotas 三张表。"""

    plan: str
    status: str
    credits_used: int
    credits_total: int
    current_period_end: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    tenant: TenantQuotaPreview


# ── /billing/plan ───────────────────────────────────────────────────────────


@router.get("/billing/plan", response_model=BillingPlanV2Out)
async def get_billing_plan(current_user: CurrentUser, db: DB) -> BillingPlanV2Out:
    """前端 /app/billing 页面用：拿当前 plan + tenant 真实配额。

    注意：plan 字段以 `users.plan` 为准（webhook 已更新）；tenant_quotas 可能滞后
    一次请求（用户刚跳回页面时 webhook 还在路上），前端可在 success_url 带 session_id
    检测后等 1-2s 再 refetch。
    """
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .order_by(Subscription.created_at.desc())
    )
    sub = sub_result.scalar_one_or_none()

    plan = current_user.plan or "free"
    tctx = pipeline_tenant.resolve_tenant_context(current_user.id, user_plan=plan)
    snap = get_or_create_tenant(
        tctx.tenant_id, plan=tctx.plan, display_name=tctx.display_name
    )

    return BillingPlanV2Out(
        plan=plan,
        status=sub.status if sub else "free",
        credits_used=current_user.credits_used,
        credits_total=current_user.credits_total,
        current_period_end=sub.current_period_end.isoformat() if sub and sub.current_period_end else None,
        stripe_customer_id=sub.stripe_customer_id if sub else None,
        tenant=TenantQuotaPreview(
            tenant_id=snap.tenant_id,
            tenant_plan=snap.plan,
            monthly_limit_usd=snap.monthly_limit_usd,
            current_period_usage_usd=snap.current_period_usage_usd,
            concurrent_max=snap.concurrent_max,
        ),
    )


# ── /billing/checkout-session ───────────────────────────────────────────────


@router.post("/billing/checkout-session", response_model=CheckoutResponse)
async def create_checkout_session_endpoint(
    body: CheckoutRequest, current_user: CurrentUser, db: DB
) -> CheckoutResponse:
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .where(Subscription.stripe_customer_id.isnot(None))
        .order_by(Subscription.created_at.desc())
    )
    sub = sub_result.scalar_one_or_none()
    customer_id = sub.stripe_customer_id if sub else None

    settings = get_settings()
    success_url = body.success_url or f"{settings.frontend_url}/app/billing"
    cancel_url = body.cancel_url or f"{settings.frontend_url}/app/billing"

    try:
        session = create_checkout_session(
            plan=body.plan,
            user_id=current_user.id,
            user_email=current_user.email,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_id=customer_id,
        )
    except StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        logger.exception("stripe checkout failed user=%s plan=%s", current_user.id, body.plan)
        raise HTTPException(
            status_code=502,
            detail=f"stripe error: {getattr(exc, 'user_message', None) or str(exc)}",
        ) from exc

    return CheckoutResponse(checkout_url=session["url"])


# 向后兼容旧路径（前端 /settings/billing v1 mock 可能仍调 /billing/checkout）
@router.post("/billing/checkout", response_model=CheckoutResponse, include_in_schema=False)
async def create_checkout_legacy(
    body: CheckoutRequest, current_user: CurrentUser, db: DB
) -> CheckoutResponse:
    return await create_checkout_session_endpoint(body, current_user, db)


# ── /billing/portal-session ─────────────────────────────────────────────────


@router.post("/billing/portal-session", response_model=PortalResponse)
async def create_portal_session_endpoint(
    current_user: CurrentUser, db: DB
) -> PortalResponse:
    sub_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id)
        .where(Subscription.stripe_customer_id.isnot(None))
        .order_by(Subscription.created_at.desc())
    )
    sub = sub_result.scalar_one_or_none()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer found. Please upgrade via checkout first.",
        )

    settings = get_settings()
    return_url = f"{settings.frontend_url}/app/billing"
    try:
        session = create_portal_session(
            customer_id=sub.stripe_customer_id, return_url=return_url
        )
    except StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
        logger.exception("stripe portal failed user=%s", current_user.id)
        raise HTTPException(
            status_code=502,
            detail=f"stripe error: {getattr(exc, 'user_message', None) or str(exc)}",
        ) from exc
    return PortalResponse(portal_url=session["url"])


# 向后兼容旧路径
@router.post("/billing/portal", response_model=PortalResponse, include_in_schema=False)
async def create_portal_legacy(current_user: CurrentUser, db: DB) -> PortalResponse:
    return await create_portal_session_endpoint(current_user, db)


# ── /billing/webhook ────────────────────────────────────────────────────────


@router.post("/billing/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request) -> dict:
    """接 stripe webhook。

    流程：
    1. 读 raw body（必须 raw，stripe 签名校验依赖原始字节）
    2. verify_webhook_event 验签
    3. handle_webhook_event 派发到对应 handler；handler 内部调
       `_set_user_plan` + `sync_user_plan`，把 plan + tenant_quotas + 桶一并 bump

    返 200 + handler 结果（即使 ignored 也返 200，避免 stripe 无限重试）；
    校验失败返 400（stripe 会重试，便于本地 stripe listen 联调时看到错误）。
    """
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    try:
        event = verify_webhook_event(payload, sig)
    except StripeNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
        logger.warning("stripe webhook signature verify failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature") from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("stripe webhook parse failed")
        raise HTTPException(status_code=400, detail=f"webhook parse error: {exc}") from exc

    # stripe.Event 是 dict-like；转成普通 dict 兼容 handler 单测
    event_dict = dict(event)
    try:
        result = handle_webhook_event(event_dict)
    except Exception:  # noqa: BLE001
        logger.exception("billing webhook handler crashed event=%s type=%s",
                         event_dict.get("id"), event_dict.get("type"))
        # 不向 stripe 返 5xx：避免无限重试；记日志由人手对账
        return {"received": True, "handled": False, "error": "handler crashed"}

    return {"received": True, **result}
