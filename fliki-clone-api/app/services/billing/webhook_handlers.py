"""Stripe webhook 事件 → DB（subscriptions / users）+ tenant_sync 派发。

事件支持矩阵（Track-11 + Track-16 退款）
---------------------------------------
| event                              | 操作                                                                |
|------------------------------------|---------------------------------------------------------------------|
| checkout.session.completed         | upsert subscriptions + users.plan = paid_plan + sync_user_plan      |
| customer.subscription.updated      | 跟随 stripe 把 plan/status/period_end 写回 + 必要时 sync_user_plan  |
| customer.subscription.deleted      | subscriptions.status='canceled' + users.plan='free' + sync_user_plan|
| invoice.payment_failed             | subscriptions.status='past_due'（不动 plan，让 stripe 重试）        |
| charge.refunded                    | subscriptions.refunded_at=NOW() 打标；**不动** tenant_quotas        |

幂等：subscriptions.stripe_sub_id 唯一；同一事件重发只 UPDATE 不重复 INSERT。

charge.refunded 设计取舍（Track-16）
------------------------------------
- 只打 `refunded_at` 标，**不**回滚 `tenant_quotas` / `users.plan`：当月已用配额
  对应的真实成本无法追回，强制把 limit 清零会让用户当月已起的 run 中途挂掉。
- 解析 subscription：优先看 charge.metadata.subscription_id（手工触发可指定）；
  其次 invoice → subscription（stripe 会在 charge.invoice 字段里给 invoice id，
  但本 webhook 仅看到 charge object，invoice 字段是 invoice_id 不是 sub_id；
  v1 用 stripe_customer_id 反查最新 active sub 兜底，足够覆盖单订阅用户场景）。
- 不抛异常：任何解析失败返 `{handled: True, matched: 0, reason: ...}`，避免
  stripe 把 webhook 反复重投打满 worker；后续 ops 用 charge.id 人工对账即可。

不在这里做的：
- 退款 → 月度配额自动回滚：见上；留给 L-04 ops 工具
- 给用户发邮件通知：留 follow-up（接 fastapi-mail / Resend）
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

from . import stripe_client
from .tenant_sync import TenantSyncResult, sync_user_plan

logger = logging.getLogger(__name__)


# ── 入口 ─────────────────────────────────────────────────────────────────────


def handle_webhook_event(event: dict[str, Any]) -> dict[str, Any]:
    """主分发器；返回结构化结果便于日志 / 测试断言。

    event 是 stripe SDK 验签后返回的 Event（dict 兼容；既支持真实 stripe.Event
    对象也支持手工 mock 的 dict）。
    未知 event 返 `{handled: False}`，router 仍回 200（stripe 不再重试）。
    """
    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}
    event_id = event.get("id", "?")

    if event_type == "checkout.session.completed":
        return _handle_checkout_completed(obj, event_id=event_id)
    if event_type == "customer.subscription.updated":
        return _handle_subscription_updated(obj, event_id=event_id)
    if event_type == "customer.subscription.deleted":
        return _handle_subscription_deleted(obj, event_id=event_id)
    if event_type == "invoice.payment_failed":
        return _handle_invoice_payment_failed(obj, event_id=event_id)
    if event_type == "charge.refunded":
        return _handle_charge_refunded(obj, event_id=event_id)

    logger.info("billing webhook ignored type=%s id=%s", event_type, event_id)
    return {"handled": False, "type": event_type, "id": event_id}


# ── checkout.session.completed ───────────────────────────────────────────────


def _handle_checkout_completed(session: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """用户在 Stripe Checkout 完成支付后的「真升级」入口。

    metadata 必须包含 `user_id` + `plan`（在 create_checkout_session 时塞入）；
    没有就退回 ignore + 警告（避免野生 webhook 把随机用户升级）。
    """
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id") or session.get("client_reference_id")
    plan = metadata.get("plan") or "standard"
    customer_id = session.get("customer")
    sub_id = session.get("subscription")

    if not user_id:
        logger.warning("checkout.session.completed missing user_id event=%s", event_id)
        return {"handled": False, "reason": "missing user_id", "id": event_id}

    _upsert_subscription(
        user_id=user_id,
        stripe_sub_id=sub_id,
        stripe_customer_id=customer_id,
        plan=plan,
        status="active",
        current_period_end=None,  # subscription.updated 会带准确时间
    )
    _set_user_plan(user_id=user_id, plan=plan)
    sync = sync_user_plan(user_id, plan)

    logger.info(
        "billing checkout completed event=%s user=%s plan=%s sub=%s tenant=%s",
        event_id,
        user_id,
        plan,
        sub_id,
        sync.tenant_id,
    )
    return {
        "handled": True,
        "type": "checkout.session.completed",
        "user_id": user_id,
        "plan": plan,
        "sync": _sync_to_dict(sync),
    }


# ── customer.subscription.updated ────────────────────────────────────────────


def _handle_subscription_updated(sub: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """订阅级变更：plan 切换、状态切换、续期等。

    plan 变化（standard → premium / premium → standard）必须重新 sync 配额，
    避免「升级了但月度额度没涨」的问题。
    """
    sub_id = sub.get("id")
    if not sub_id:
        return {"handled": False, "reason": "missing subscription id", "id": event_id}

    metadata = sub.get("metadata") or {}
    customer_id = sub.get("customer")
    status = sub.get("status") or "active"
    current_period_end = _maybe_ts(sub.get("current_period_end"))

    # plan 解析优先级：metadata.plan > items.data[0].price.id 反查
    plan = metadata.get("plan") or _plan_from_subscription_items(sub)

    user_id = metadata.get("user_id") or _user_id_for_sub(sub_id)
    if not user_id:
        logger.warning("subscription.updated cannot resolve user event=%s sub=%s", event_id, sub_id)
        return {"handled": False, "reason": "user not found", "sub_id": sub_id}

    _upsert_subscription(
        user_id=user_id,
        stripe_sub_id=sub_id,
        stripe_customer_id=customer_id,
        plan=plan or "standard",
        status=status,
        current_period_end=current_period_end,
    )

    sync_result: Optional[TenantSyncResult] = None
    if plan and status == "active":
        _set_user_plan(user_id=user_id, plan=plan)
        sync_result = sync_user_plan(user_id, plan)

    logger.info(
        "billing subscription updated event=%s user=%s sub=%s plan=%s status=%s",
        event_id,
        user_id,
        sub_id,
        plan,
        status,
    )
    return {
        "handled": True,
        "type": "customer.subscription.updated",
        "user_id": user_id,
        "plan": plan,
        "status": status,
        "sync": _sync_to_dict(sync_result) if sync_result else None,
    }


# ── customer.subscription.deleted ────────────────────────────────────────────


def _handle_subscription_deleted(sub: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """退订（end of billing period 后 stripe 删 subscription）→ 回 free。"""
    sub_id = sub.get("id")
    if not sub_id:
        return {"handled": False, "reason": "missing subscription id", "id": event_id}

    user_id = (sub.get("metadata") or {}).get("user_id") or _user_id_for_sub(sub_id)
    if not user_id:
        logger.warning("subscription.deleted cannot resolve user event=%s sub=%s", event_id, sub_id)
        # 仍把 row mark canceled，避免「孤儿 active」
        _mark_subscription_status(sub_id=sub_id, status="canceled")
        return {"handled": True, "type": "customer.subscription.deleted", "user_id": None}

    _mark_subscription_status(sub_id=sub_id, status="canceled")
    _set_user_plan(user_id=user_id, plan="free")
    sync = sync_user_plan(user_id, "free")

    logger.info(
        "billing subscription canceled event=%s user=%s sub=%s tenant=%s",
        event_id,
        user_id,
        sub_id,
        sync.tenant_id,
    )
    return {
        "handled": True,
        "type": "customer.subscription.deleted",
        "user_id": user_id,
        "plan": "free",
        "sync": _sync_to_dict(sync),
    }


# ── invoice.payment_failed ───────────────────────────────────────────────────


def _handle_invoice_payment_failed(invoice: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """续费扣款失败：把 subscription 标 past_due，不动 plan / 配额；
    stripe 自带 dunning 流程会继续重试。"""
    sub_id = invoice.get("subscription")
    if not sub_id:
        return {"handled": False, "reason": "missing subscription id", "id": event_id}
    _mark_subscription_status(sub_id=sub_id, status="past_due")
    logger.warning("billing invoice payment_failed event=%s sub=%s -> past_due", event_id, sub_id)
    return {"handled": True, "type": "invoice.payment_failed", "sub_id": sub_id}


# ── charge.refunded ─────────────────────────────────────────────────────────


def _handle_charge_refunded(charge: dict[str, Any], *, event_id: str) -> dict[str, Any]:
    """退款打标。**不动** tenant_quotas / users.plan（v1 故意保留当月已扣额度）。

    解析订阅的优先级（match-first，遇到第一个非空就用）：
    1. ``charge.metadata.subscription_id`` —— ops 手工 trigger 时显式带
    2. ``charge.invoice`` 反查 stripe API —— v1 不做（避免在 webhook 同步路径
       里再发 stripe 出站调用，否则 stripe 不可达就把 webhook 回 5xx）
    3. ``charge.customer`` —— 反查最新 active subscription（单订阅用户场景足够）

    都解析不到时 ``handled=True`` 但 ``matched=0``，写日志让 ops 用 charge_id 对账。
    幂等：同一 charge 重复触发只是把 ``refunded_at`` 重写为 NOW，无副作用。
    """
    charge_id = charge.get("id")
    metadata = charge.get("metadata") or {}
    explicit_sub_id = metadata.get("subscription_id")
    customer_id = charge.get("customer")

    matched = 0
    matched_sub_id: Optional[str] = None
    if explicit_sub_id:
        matched = _mark_subscription_refunded_by_sub_id(explicit_sub_id)
        if matched:
            matched_sub_id = explicit_sub_id
    if matched == 0 and customer_id:
        matched_sub_id = _mark_latest_subscription_refunded_by_customer(customer_id)
        if matched_sub_id:
            matched = 1

    if matched == 0:
        logger.warning(
            "billing charge.refunded unmatched event=%s charge=%s customer=%s sub_meta=%s",
            event_id,
            charge_id,
            customer_id,
            explicit_sub_id,
        )
        return {
            "handled": True,
            "type": "charge.refunded",
            "matched": 0,
            "charge_id": charge_id,
            "reason": "no subscription resolved from metadata/customer",
        }

    logger.info(
        "billing charge.refunded matched event=%s charge=%s sub=%s",
        event_id,
        charge_id,
        matched_sub_id,
    )
    return {
        "handled": True,
        "type": "charge.refunded",
        "matched": matched,
        "charge_id": charge_id,
        "sub_id": matched_sub_id,
    }


# ── DB helpers（sync engine，与 quota.py 一致）───────────────────────────────


def _engine():
    return create_engine(get_settings().database_url_sync)


def _upsert_subscription(
    *,
    user_id: str,
    stripe_sub_id: Optional[str],
    stripe_customer_id: Optional[str],
    plan: str,
    status: str,
    current_period_end: Optional[datetime],
) -> None:
    """按 stripe_sub_id 幂等 upsert。stripe_sub_id 缺失（极少）退化为按 user_id 一行。"""
    engine = _engine()
    with engine.begin() as conn:
        if stripe_sub_id:
            existing = conn.execute(
                text("SELECT id FROM subscriptions WHERE stripe_sub_id = :sid"),
                {"sid": stripe_sub_id},
            ).fetchone()
        else:
            existing = conn.execute(
                text(
                    "SELECT id FROM subscriptions WHERE user_id = :uid ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": user_id},
            ).fetchone()

        if existing:
            conn.execute(
                text(
                    """
                    UPDATE subscriptions
                       SET stripe_sub_id = COALESCE(:sid, stripe_sub_id),
                           stripe_customer_id = COALESCE(:cid, stripe_customer_id),
                           plan = :plan,
                           status = :status,
                           current_period_end = COALESCE(:pend, current_period_end),
                           updated_at = NOW()
                     WHERE id = :id
                    """
                ),
                {
                    "id": existing[0],
                    "sid": stripe_sub_id,
                    "cid": stripe_customer_id,
                    "plan": plan,
                    "status": status,
                    "pend": current_period_end,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO subscriptions
                        (id, user_id, stripe_sub_id, stripe_customer_id,
                         plan, status, current_period_end, created_at, updated_at)
                    VALUES
                        (:id, :uid, :sid, :cid, :plan, :status, :pend, NOW(), NOW())
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": user_id,
                    "sid": stripe_sub_id,
                    "cid": stripe_customer_id,
                    "plan": plan,
                    "status": status,
                    "pend": current_period_end,
                },
            )


def _mark_subscription_status(*, sub_id: str, status: str) -> None:
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE subscriptions
                   SET status = :status, updated_at = NOW()
                 WHERE stripe_sub_id = :sid
                """
            ),
            {"sid": sub_id, "status": status},
        )


def _mark_subscription_refunded_by_sub_id(sub_id: str) -> int:
    """按 stripe_sub_id 写 refunded_at；返回受影响行数（应为 0 或 1）。"""
    engine = _engine()
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE subscriptions
                   SET refunded_at = NOW(), updated_at = NOW()
                 WHERE stripe_sub_id = :sid
                """
            ),
            {"sid": sub_id},
        )
        return result.rowcount or 0


def _mark_latest_subscription_refunded_by_customer(customer_id: str) -> Optional[str]:
    """按 stripe_customer_id 找最新一条订阅（按 created_at DESC）打标，返回 sub_id；
    一行都没有时返 None。
    """
    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, stripe_sub_id FROM subscriptions
                 WHERE stripe_customer_id = :cid
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).fetchone()
        if not row:
            return None
        conn.execute(
            text(
                """
                UPDATE subscriptions
                   SET refunded_at = NOW(), updated_at = NOW()
                 WHERE id = :id
                """
            ),
            {"id": row[0]},
        )
        return row[1]


def _set_user_plan(*, user_id: str, plan: str) -> None:
    """同步 users.plan + credits_total（按 plan 给一个粗粒度 credits 数；
    真实 minutes 配额看 tenant_quotas，credits 仅用于前端 dashboard 老 UI）。"""
    credits_by_plan = {"free": 5, "standard": 60, "premium": 200}
    credits = credits_by_plan.get(plan, 5)
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE users
                   SET plan = :plan,
                       credits_total = :credits,
                       updated_at = NOW()
                 WHERE id = :uid
                """
            ),
            {"uid": user_id, "plan": plan, "credits": credits},
        )


def _user_id_for_sub(sub_id: str) -> Optional[str]:
    engine = _engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT user_id FROM subscriptions WHERE stripe_sub_id = :sid"),
            {"sid": sub_id},
        ).fetchone()
    return row[0] if row else None


def _plan_from_subscription_items(sub: dict[str, Any]) -> Optional[str]:
    """优先 metadata.plan；否则取 items.data[0].price.id 反查 settings 配置。"""
    items = (sub.get("items") or {}).get("data") or []
    if not items:
        return None
    price = (items[0] or {}).get("price") or {}
    return stripe_client.plan_for_price_id(price.get("id"))


def _maybe_ts(ts: Any) -> Optional[datetime]:
    """stripe unix epoch → tz-aware UTC datetime；None / 非数字 → None。"""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _sync_to_dict(result: Optional[TenantSyncResult]) -> Optional[dict[str, Any]]:
    if not result:
        return None
    snap = result.snapshot
    return {
        "tenant_id": result.tenant_id,
        "plan": result.plan,
        "monthly_limit_usd": snap.monthly_limit_usd if snap else None,
        "concurrent_max": snap.concurrent_max if snap else None,
        "skipped_reason": result.skipped_reason,
    }


__all__ = ["handle_webhook_event"]
