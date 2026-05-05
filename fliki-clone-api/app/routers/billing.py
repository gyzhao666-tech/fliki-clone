import stripe
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.billing import Subscription
from app.schemas import (
    BillingPlanOut,
    CheckoutRequest,
    CheckoutResponse,
    MessageResponse,
    PortalResponse,
)

router = APIRouter(tags=["Billing"])
settings = get_settings()

stripe.api_key = settings.stripe_secret_key

PLAN_PRICE_MAP = {
    "standard": settings.stripe_price_standard,
    "premium": settings.stripe_price_premium,
}


@router.get("/billing/plan", response_model=BillingPlanOut)
async def get_billing_plan(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == current_user.id, Subscription.status == "active")
        .order_by(Subscription.created_at.desc())
    )
    sub = result.scalar_one_or_none()
    return BillingPlanOut(
        plan=current_user.plan,
        status=sub.status if sub else "free",
        credits_used=current_user.credits_used,
        credits_total=current_user.credits_total,
        current_period_end=sub.current_period_end if sub else None,
        stripe_customer_id=sub.stripe_customer_id if sub else None,
    )


@router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_checkout(body: CheckoutRequest, current_user: CurrentUser, db: DB):
    price_id = PLAN_PRICE_MAP.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    sub = result.scalar_one_or_none()
    customer_id = sub.stripe_customer_id if sub else None

    session = stripe.checkout.Session.create(
        customer=customer_id,
        customer_email=None if customer_id else current_user.email,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=body.success_url + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=body.cancel_url,
        metadata={"user_id": current_user.id, "plan": body.plan},
    )
    return CheckoutResponse(checkout_url=session.url)


@router.post("/billing/portal", response_model=PortalResponse)
async def create_portal(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id, Subscription.stripe_customer_id.isnot(None))
    )
    sub = result.scalar_one_or_none()
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No active subscription found")

    session = stripe.billing_portal.Session.create(
        customer=sub.stripe_customer_id,
        return_url=f"{settings.frontend_url}/settings/billing",
    )
    return PortalResponse(portal_url=session.url)


@router.post("/billing/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: DB):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        plan = session.get("metadata", {}).get("plan", "standard")
        customer_id = session.get("customer")
        sub_id = session.get("subscription")

        if user_id:
            from app.models.user import User
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.plan = plan
                user.credits_total = 60 if plan == "premium" else 20

                sub = Subscription(
                    user_id=user_id,
                    stripe_sub_id=sub_id,
                    stripe_customer_id=customer_id,
                    plan=plan,
                    status="active",
                )
                db.add(sub)
                await db.commit()

    elif event["type"] == "customer.subscription.deleted":
        sub_data = event["data"]["object"]
        result = await db.execute(
            select(Subscription).where(Subscription.stripe_sub_id == sub_data["id"])
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            from app.models.user import User
            user_result = await db.execute(select(User).where(User.id == sub.user_id))
            user = user_result.scalar_one_or_none()
            if user:
                user.plan = "free"
                user.credits_total = 5
            await db.commit()

    return {"received": True}
