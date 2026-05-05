"""Stripe webhook handler 集成测试（Track-16）。

覆盖矩阵
--------
1. ``test_checkout_session_completed_inserts_subscription_and_syncs_quota``
   - upsert subscriptions（含 `stripe_sub_id` 唯一）
   - users.plan = 'standard'
   - tenant_sync 把 tenant_quotas.plan 切到 standard
2. ``test_subscription_updated_switches_plan_and_bumps_quota``
   - plan: standard → premium，monthly_limit_usd / concurrent_max 触发 bump
3. ``test_subscription_deleted_marks_canceled_and_drops_user_to_free``
   - subscriptions.status='canceled'，users.plan='free'，tenant.plan='free'
4. ``test_invoice_payment_failed_sets_past_due_only``
   - subscriptions.status='past_due'，**不**改 plan / 配额
5. ``test_charge_refunded_marks_refunded_at_without_touching_quota``
   - subscriptions.refunded_at 写入；tenant_quotas.plan 与 monthly_limit_usd **不变**
6. ``test_unknown_event_returns_handled_false``
   - 未知 event type → `handled=False`（router 仍 200，不抛）

设计取舍
-------
- 不污染 conftest：``make_event(...)`` 工厂私有在本文件
- 强 mock ``stripe_client.plan_for_price_id``（避免依赖 .env 真 STRIPE_PRICE_*）
- 直接走 handle_webhook_event 入口；DB 走真 PG（与 tests/conftest.py 一致）
- 所有 fixture 走 conftest 的 ``temp_user`` / ``temp_tenant``，case 自动清理
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Optional

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ── helper ────────────────────────────────────────────────────────────────────


def make_event(
    event_type: str,
    *,
    obj: Optional[dict[str, Any]] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    """构造一个最小可用的 stripe Event dict（兼容 SDK Event 对象的访问语法）。"""
    return {
        "id": event_id or f"evt_test_{uuid.uuid4().hex[:8]}",
        "type": event_type,
        "data": {"object": obj or {}},
    }


def _seed_tenant_for_user(pg_engine, *, tenant_id: str, plan: str = "free") -> None:
    """webhook 处理需要 tenant_quotas 行存在；显式 seed，避免 sync 路径里第一个
    SELECT 看到空行后再 fallback。
    """
    from app.services.pipeline.tenant import plan_defaults

    d = plan_defaults(plan)
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM tenant_quotas WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO tenant_quotas
                    (tenant_id, plan, monthly_limit_usd, current_period_usage_usd,
                     current_period_start, concurrent_max, display_name,
                     created_at, updated_at)
                VALUES
                    (:t, :pl, :lim, 0, NOW(), :cm, :dn, NOW(), NOW())
                """
            ),
            {
                "t": tenant_id,
                "pl": plan,
                "lim": float(d["monthly_limit_usd"]),
                "cm": int(d["concurrent_max"]),
                "dn": "pytest tenant",
            },
        )


def _fetch_sub(pg_engine, *, sub_id: str) -> Optional[dict[str, Any]]:
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, user_id, stripe_sub_id, stripe_customer_id, plan,
                       status, current_period_end, refunded_at
                  FROM subscriptions
                 WHERE stripe_sub_id = :sid
                """
            ),
            {"sid": sub_id},
        ).mappings().fetchone()
    return dict(row) if row else None


def _fetch_user_plan(pg_engine, *, user_id: str) -> Optional[str]:
    with pg_engine.connect() as conn:
        return conn.execute(
            text("SELECT plan FROM users WHERE id = :u"),
            {"u": user_id},
        ).scalar_one_or_none()


def _fetch_tenant(pg_engine, *, tenant_id: str) -> Optional[dict[str, Any]]:
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT tenant_id, plan, monthly_limit_usd, concurrent_max
                  FROM tenant_quotas
                 WHERE tenant_id = :t
                """
            ),
            {"t": tenant_id},
        ).mappings().fetchone()
    return dict(row) if row else None


@pytest.fixture
def billing_user(pg_engine, temp_user):
    """temp_user + 对应的 tenant_quotas 行（u:{user_id} 命名空间，free 默认）。
    teardown 走 temp_user 自带；但 tenant_quotas 行需要本 fixture 显式删掉，
    否则 (tenant_id) 主键会跨 case 复用。
    """
    tenant_id = f"u:{temp_user['id']}"
    _seed_tenant_for_user(pg_engine, tenant_id=tenant_id, plan="free")
    yield {**temp_user, "tenant_id": tenant_id}
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM provider_concurrency_buckets WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.execute(
            text("DELETE FROM tenant_quotas WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
        conn.execute(
            text("DELETE FROM subscriptions WHERE user_id = :u"),
            {"u": temp_user["id"]},
        )


# ── 1. checkout.session.completed ────────────────────────────────────────────


def test_checkout_session_completed_inserts_subscription_and_syncs_quota(
    pg_engine, billing_user, monkeypatch
):
    """端到端：webhook 收到 checkout.session.completed 后，
    subscriptions / users.plan / tenant_quotas.plan 三处全部对齐到 standard。
    """
    from app.services.billing import webhook_handlers

    # 主动清缓存避免 free 残留
    from app.services.pipeline import tenant as ptenant

    ptenant.clear_cache()

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    event = make_event(
        "checkout.session.completed",
        obj={
            "id": f"cs_test_{uuid.uuid4().hex[:8]}",
            "customer": customer_id,
            "subscription": sub_id,
            "client_reference_id": billing_user["id"],
            "metadata": {"user_id": billing_user["id"], "plan": "standard"},
        },
    )

    result = webhook_handlers.handle_webhook_event(event)
    assert result["handled"] is True
    assert result["type"] == "checkout.session.completed"
    assert result["plan"] == "standard"
    assert result["sync"]["tenant_id"] == billing_user["tenant_id"]
    assert result["sync"]["plan"] == "standard"

    sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert sub is not None
    assert sub["user_id"] == billing_user["id"]
    assert sub["plan"] == "standard"
    assert sub["status"] == "active"
    assert sub["stripe_customer_id"] == customer_id
    assert sub["refunded_at"] is None  # 新订阅未退款

    assert _fetch_user_plan(pg_engine, user_id=billing_user["id"]) == "standard"

    tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert tenant is not None
    assert tenant["plan"] == "standard"
    # standard 默认 monthly_limit_usd >= free，bump 后必非零
    assert tenant["monthly_limit_usd"] > 10.0


# ── 2. customer.subscription.updated ─────────────────────────────────────────


def test_subscription_updated_switches_plan_and_bumps_quota(
    pg_engine, billing_user, monkeypatch
):
    """先把 tenant 落到 standard，再发一条 subscription.updated → premium，
    断 plan 切换 + monthly_limit_usd / concurrent_max 触发 bump。
    """
    from app.services.billing import webhook_handlers
    from app.services.pipeline import tenant as ptenant

    ptenant.clear_cache()

    # Step 1: seed 一条 standard 订阅
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    pre = make_event(
        "checkout.session.completed",
        obj={
            "id": f"cs_test_{uuid.uuid4().hex[:8]}",
            "customer": customer_id,
            "subscription": sub_id,
            "metadata": {"user_id": billing_user["id"], "plan": "standard"},
        },
    )
    webhook_handlers.handle_webhook_event(pre)

    standard_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert standard_tenant["plan"] == "standard"
    standard_limit = standard_tenant["monthly_limit_usd"]
    standard_concurrent = standard_tenant["concurrent_max"]

    # Step 2: subscription.updated → premium
    update_event = make_event(
        "customer.subscription.updated",
        obj={
            "id": sub_id,
            "customer": customer_id,
            "status": "active",
            "current_period_end": int(time.time()) + 30 * 86400,
            "metadata": {"user_id": billing_user["id"], "plan": "premium"},
            "items": {"data": [{"price": {"id": "price_premium_test"}}]},
        },
    )
    result = webhook_handlers.handle_webhook_event(update_event)
    assert result["handled"] is True
    assert result["type"] == "customer.subscription.updated"
    assert result["plan"] == "premium"
    assert result["status"] == "active"

    sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert sub["plan"] == "premium"
    assert sub["status"] == "active"
    assert sub["current_period_end"] is not None

    assert _fetch_user_plan(pg_engine, user_id=billing_user["id"]) == "premium"

    bumped = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert bumped["plan"] == "premium"
    # premium >= standard：bump 至少不下降
    assert bumped["monthly_limit_usd"] >= standard_limit
    assert bumped["concurrent_max"] >= standard_concurrent


# ── 3. customer.subscription.deleted ─────────────────────────────────────────


def test_subscription_deleted_marks_canceled_and_drops_user_to_free(
    pg_engine, billing_user
):
    """端到端：先升 standard → 收到 subscription.deleted → 全链路回 free。
    特意验证 tenant_quotas.plan='free'（升级 bump 过的 monthly_limit_usd
    按设计**保留**，避免突然削掉用户当月已扣的额度）。
    """
    from app.services.billing import webhook_handlers
    from app.services.pipeline import tenant as ptenant

    ptenant.clear_cache()

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    webhook_handlers.handle_webhook_event(
        make_event(
            "checkout.session.completed",
            obj={
                "customer": customer_id,
                "subscription": sub_id,
                "metadata": {"user_id": billing_user["id"], "plan": "standard"},
            },
        )
    )

    pre_delete_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    bumped_limit = pre_delete_tenant["monthly_limit_usd"]

    delete_event = make_event(
        "customer.subscription.deleted",
        obj={
            "id": sub_id,
            "customer": customer_id,
            "status": "canceled",
            "metadata": {"user_id": billing_user["id"]},
        },
    )
    result = webhook_handlers.handle_webhook_event(delete_event)
    assert result["handled"] is True
    assert result["plan"] == "free"
    assert result["sync"]["plan"] == "free"

    sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert sub["status"] == "canceled"

    assert _fetch_user_plan(pg_engine, user_id=billing_user["id"]) == "free"

    tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert tenant["plan"] == "free"
    # 降级保留：monthly_limit_usd 不应被砍
    assert tenant["monthly_limit_usd"] >= bumped_limit


# ── 4. invoice.payment_failed ────────────────────────────────────────────────


def test_invoice_payment_failed_sets_past_due_only(pg_engine, billing_user):
    """续费扣款失败：subscriptions.status='past_due'，**不**动 plan / users.plan / tenant。"""
    from app.services.billing import webhook_handlers
    from app.services.pipeline import tenant as ptenant

    ptenant.clear_cache()

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    webhook_handlers.handle_webhook_event(
        make_event(
            "checkout.session.completed",
            obj={
                "customer": customer_id,
                "subscription": sub_id,
                "metadata": {"user_id": billing_user["id"], "plan": "standard"},
            },
        )
    )
    pre_user_plan = _fetch_user_plan(pg_engine, user_id=billing_user["id"])
    pre_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])

    fail_event = make_event(
        "invoice.payment_failed",
        obj={
            "id": f"in_test_{uuid.uuid4().hex[:8]}",
            "subscription": sub_id,
            "customer": customer_id,
            "amount_due": 999,
        },
    )
    result = webhook_handlers.handle_webhook_event(fail_event)
    assert result["handled"] is True
    assert result["type"] == "invoice.payment_failed"
    assert result["sub_id"] == sub_id

    sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert sub["status"] == "past_due"
    # plan 不应被动
    assert sub["plan"] == "standard"
    # users.plan / tenant 不动
    assert _fetch_user_plan(pg_engine, user_id=billing_user["id"]) == pre_user_plan
    post_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert post_tenant["plan"] == pre_tenant["plan"]
    assert post_tenant["monthly_limit_usd"] == pre_tenant["monthly_limit_usd"]


# ── 5. charge.refunded ───────────────────────────────────────────────────────


def test_charge_refunded_marks_refunded_at_without_touching_quota(
    pg_engine, billing_user
):
    """退款打标：subscriptions.refunded_at 写入；tenant_quotas / users.plan / sub.plan
    全部不变（v1 故意保留当月配额，由 ops 评估）。
    """
    from app.services.billing import webhook_handlers
    from app.services.pipeline import tenant as ptenant

    ptenant.clear_cache()

    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    webhook_handlers.handle_webhook_event(
        make_event(
            "checkout.session.completed",
            obj={
                "customer": customer_id,
                "subscription": sub_id,
                "metadata": {"user_id": billing_user["id"], "plan": "standard"},
            },
        )
    )

    pre_sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert pre_sub["refunded_at"] is None
    pre_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    pre_user_plan = _fetch_user_plan(pg_engine, user_id=billing_user["id"])

    refund_event = make_event(
        "charge.refunded",
        obj={
            "id": f"ch_test_{uuid.uuid4().hex[:8]}",
            "customer": customer_id,
            "amount_refunded": 999,
            "metadata": {"subscription_id": sub_id},
        },
    )
    result = webhook_handlers.handle_webhook_event(refund_event)
    assert result["handled"] is True
    assert result["type"] == "charge.refunded"
    assert result["matched"] == 1
    assert result["sub_id"] == sub_id

    post_sub = _fetch_sub(pg_engine, sub_id=sub_id)
    assert post_sub["refunded_at"] is not None
    # plan / status 不动
    assert post_sub["plan"] == "standard"
    assert post_sub["status"] == "active"

    # users.plan / tenant_quotas 完全不变
    assert _fetch_user_plan(pg_engine, user_id=billing_user["id"]) == pre_user_plan
    post_tenant = _fetch_tenant(pg_engine, tenant_id=billing_user["tenant_id"])
    assert post_tenant["plan"] == pre_tenant["plan"]
    assert post_tenant["monthly_limit_usd"] == pre_tenant["monthly_limit_usd"]
    assert post_tenant["concurrent_max"] == pre_tenant["concurrent_max"]


# ── 6. unknown event type ────────────────────────────────────────────────────


@pytest.mark.unit
def test_unknown_event_returns_handled_false():
    """未知 event 不抛异常，返 handled=False；router 拿到此结果仍回 200，
    避免 stripe 反复重投把 worker 打满。"""
    from app.services.billing import webhook_handlers

    event = make_event(
        "customer.discount.created",
        obj={"id": "di_test", "discount": {"coupon": "TENPCT"}},
    )
    result = webhook_handlers.handle_webhook_event(event)
    assert result["handled"] is False
    assert result["type"] == "customer.discount.created"
    assert result["id"] == event["id"]
