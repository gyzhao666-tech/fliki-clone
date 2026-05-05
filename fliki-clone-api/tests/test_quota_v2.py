"""配额 v2（tenant_quotas + provider_concurrency_buckets + gateway 接入点）测试。

覆盖
----
1. ``test_tenant_quota_create_and_reserve``         tenant_quotas CRUD + reserve_tenant 超额拦截
2. ``test_tenant_quota_release_floors_at_zero``     release_tenant + GREATEST 0 兜底
3. ``test_provider_bucket_acquire_release_cycle``   acquire/release/list_buckets/ensure_bucket plan-bump
4. ``test_provider_bucket_concurrency_race``        20 个线程抢 2 槽位 —— 严格只允许 2 个 acquire 成功
5. ``test_resolve_tenant_id_anonymous_and_user``    resolve_tenant_id 三档兜底（anon / u: / cache）
6. ``test_gateway_rate_limited_when_bucket_full``   gateway.run() 桶满时返 RATE_LIMITED 不计费
7. ``test_gateway_user_id_fallback_resolves_tenant``gateway 在 request 缺 tenant_id 时用 user_id 解析

unit / integration
------------------
3-7 命中真表，标 ``integration``；5 的 anon 分支 + plan_defaults 是纯逻辑，
单独抽出 ``test_plan_defaults_table`` 标 ``unit``。
"""
from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.quota


# ── 1. plan defaults / resolver 纯逻辑 ────────────────────────────────────────


@pytest.mark.unit
def test_plan_defaults_table():
    """所有 plan 都有非零月度额度 + 并发上限；未知 plan fallback free。"""
    from app.services.pipeline.tenant import PLAN_DEFAULTS, plan_defaults

    for plan in ("free", "standard", "premium", "enterprise"):
        d = plan_defaults(plan)
        assert d["monthly_limit_usd"] > 0
        assert d["concurrent_max"] >= 1
        assert PLAN_DEFAULTS[plan]["monthly_limit_usd"] == d["monthly_limit_usd"]

    # 未知 plan → free 兜底（不抛 KeyError）
    fallback = plan_defaults("nonexistent-plan-xyz")
    assert fallback == PLAN_DEFAULTS["free"]


@pytest.mark.unit
def test_resolve_tenant_id_anonymous_branches():
    """resolve_tenant_id：空 user → anon:default；带 user 走 ws/u 分支（非空）。

    后半段实际命中 DB；这里只覆盖匿名 + cache；DB 分支单独 integration 测。
    """
    from app.services.pipeline.tenant import (
        clear_cache,
        resolve_tenant_context,
        resolve_tenant_id,
    )

    clear_cache()
    assert resolve_tenant_id(None) == "anon:default"
    assert resolve_tenant_id("") == "anon:default"

    # context 版本对匿名也要返一份合法 plan / display_name，不抛
    ctx = resolve_tenant_context(None)
    assert ctx.tenant_id == "anon:default"
    assert ctx.plan == "free"
    assert ctx.display_name == "(anonymous)"


# ── 2. tenant_quotas DB 集成 ────────────────────────────────────────────────


@pytest.mark.integration
def test_tenant_quota_create_and_reserve(temp_tenant):
    """get_or_create_tenant 第一次落库 + reserve 上限拦截。

    步骤：
    - free plan tenant_quotas 默认 monthly=10
    - reserve $4 OK；usage=4
    - reserve $7 拒绝（usage 4 + amount 7 = 11 > 10）；usage 仍是 4
    - reserve $6 OK；usage=10（边界刚好等于 limit + epsilon）
    """
    from app.services.pipeline.quota import (
        get_or_create_tenant,
        reserve_tenant,
    )

    snap = get_or_create_tenant(
        temp_tenant.tenant_id, plan="free", display_name="pytest"
    )
    assert snap.tenant_id == temp_tenant.tenant_id
    assert snap.plan == "free"
    assert snap.monthly_limit_usd == 10.0
    assert snap.current_period_usage_usd == 0.0
    assert snap.concurrent_max == 2

    r1 = reserve_tenant(temp_tenant.tenant_id, 4.0)
    assert r1.ok is True
    assert r1.tenant_snapshot.current_period_usage_usd == pytest.approx(4.0)

    r2 = reserve_tenant(temp_tenant.tenant_id, 7.0)
    assert r2.ok is False
    assert "insufficient" in (r2.reason or "")

    # 再 reserve $6 → 4+6=10 应该被允许（边界）
    r3 = reserve_tenant(temp_tenant.tenant_id, 6.0)
    assert r3.ok is True
    assert r3.tenant_snapshot.current_period_usage_usd == pytest.approx(10.0)


@pytest.mark.integration
def test_tenant_quota_release_floors_at_zero(temp_tenant, pg_engine):
    """release_tenant 超量退还时被 GREATEST(0, ...) 兜底，不会出现负 usage。"""
    from app.services.pipeline.quota import (
        get_or_create_tenant,
        release_tenant,
        reserve_tenant,
    )

    get_or_create_tenant(temp_tenant.tenant_id, plan="free")
    assert reserve_tenant(temp_tenant.tenant_id, 3.0).ok

    # 故意退超过 reserved 的量
    release_tenant(temp_tenant.tenant_id, 100.0)

    with pg_engine.connect() as conn:
        usage = conn.execute(
            text(
                "SELECT current_period_usage_usd FROM tenant_quotas "
                "WHERE tenant_id = :t"
            ),
            {"t": temp_tenant.tenant_id},
        ).scalar_one()
    assert usage == pytest.approx(0.0)


# ── 3. provider_concurrency_buckets ─────────────────────────────────────────


@pytest.mark.integration
def test_provider_bucket_acquire_release_cycle(temp_tenant):
    """acquire / release 单次往返；ensure_bucket plan-bump 自动放大不缩小。"""
    from app.services.pipeline.provider_buckets import (
        BucketFull,
        acquire,
        ensure_bucket,
        list_buckets,
        release,
    )

    pn = "siliconflow"
    snap = ensure_bucket(temp_tenant.tenant_id, pn, plan="free")
    assert snap.max_concurrent == 2  # free plan SF 桶
    assert snap.current_in_flight == 0

    snap2 = acquire(temp_tenant.tenant_id, pn, plan="free")
    assert snap2.current_in_flight == 1
    snap3 = acquire(temp_tenant.tenant_id, pn, plan="free")
    assert snap3.current_in_flight == 2

    # 第三次必抛 BucketFull
    with pytest.raises(BucketFull):
        acquire(temp_tenant.tenant_id, pn, plan="free")

    release(temp_tenant.tenant_id, pn)
    snap4 = list_buckets(temp_tenant.tenant_id)[0]
    assert snap4.current_in_flight == 1

    # plan 升级 → bump 到 premium 默认值（8）
    bumped = ensure_bucket(temp_tenant.tenant_id, pn, plan="premium")
    assert bumped.max_concurrent == 8
    # 再降级 → 不缩小（保护 SRE 已调过的桶）
    not_shrunk = ensure_bucket(temp_tenant.tenant_id, pn, plan="free")
    assert not_shrunk.max_concurrent == 8


@pytest.mark.integration
def test_provider_bucket_concurrency_race(temp_tenant):
    """20 个线程同时抢一个 max=2 的桶 —— 严格只允许 2 个 acquire 成功。

    这是 v2 的核心安全性证明：条件 UPDATE 单 SQL 即可避免 over-acquire。
    """
    from app.services.pipeline.provider_buckets import (
        BucketFull,
        acquire,
        ensure_bucket,
    )

    pn = "kling"  # free 默认 1；显式 override 到 2 让线程间真竞争
    ensure_bucket(temp_tenant.tenant_id, pn, plan="free", max_override=2)

    success_count = 0
    fail_count = 0
    lock = threading.Lock()

    def worker():
        nonlocal success_count, fail_count
        try:
            acquire(temp_tenant.tenant_id, pn, plan="free")
            with lock:
                success_count += 1
        except BucketFull:
            with lock:
                fail_count += 1

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert success_count == 2, (
        f"严格 2 槽位被打破！succ={success_count} fail={fail_count}"
    )
    assert fail_count == 18


# ── 4. gateway 接入点：rate_limited + user_id fallback ───────────────────────


def _build_fake_provider(name_value: str = "demo", action_value: str = "llm"):
    """造一个最小 BaseProvider，supports + is_available + call 返成功固定结果。"""
    from app.services.model_gateway.providers.base import BaseProvider
    from app.services.model_gateway.types import (
        CallStatus,
        ModelAction,
        ProviderName,
        RenderResult,
    )

    pn = ProviderName(name_value)
    target_action = ModelAction(action_value)

    class _FakeProvider(BaseProvider):
        name = pn

        def supports(self, action) -> bool:
            return action == target_action

        def is_available(self) -> bool:
            return True

        def call(self, request):
            return RenderResult(
                status=CallStatus.SUCCEEDED,
                provider=pn,
                output={"echo": "ok"},
                cost_usd=0.0,
            )

    return _FakeProvider()


@pytest.mark.integration
def test_gateway_rate_limited_when_bucket_full(temp_tenant):
    """构造一个全新 Gateway 实例 + 注入 fake provider；把桶 max 设为 1 + 先手动 acquire；
    再调 gateway.run() 应返 ``CallStatus.RATE_LIMITED``，不进入 provider.call。

    用 ``ProviderName.KLING``：free plan 默认 max_concurrent=1，避免 gateway 内部
    ``ensure_bucket(plan="free")`` 把 max 自动 bump 到比测试 override 更大的值
    （demo / siliconflow free 默认值都 >= 2，不适合做「桶满」测试）。

    避免污染全局 ``get_gateway()`` 单例：直接 ``Gateway()`` 构造一个测试专用实例。
    """
    from app.services.model_gateway.gateway import Gateway
    from app.services.model_gateway.types import (
        CallStatus,
        ModelAction,
        ProviderName,
        RenderRequest,
    )
    from app.services.pipeline.provider_buckets import (
        acquire,
        ensure_bucket,
        release,
    )

    gw = Gateway()
    fake = _build_fake_provider(name_value="kling", action_value="llm")
    gw.register(fake)
    # 默认路由没把 KLING 放 LLM；显式塞首位让 select_provider 命中（绕开 DEMO 没注册）
    gw._default_routing[ModelAction.LLM] = [ProviderName.KLING]

    # kling free 默认 max=1；显式 ensure 一次让行存在，然后手动 acquire 把 in_flight 拉到 max
    ensure_bucket(temp_tenant.tenant_id, "kling", plan="free")
    acquire(temp_tenant.tenant_id, "kling", plan="free")
    try:
        result = gw.run(
            RenderRequest(
                action=ModelAction.LLM,
                params={"messages": [{"role": "user", "content": "hi"}]},
                tenant_id=temp_tenant.tenant_id,
                tenant_plan="free",
            )
        )
        assert result.status == CallStatus.RATE_LIMITED, (
            f"应返 RATE_LIMITED；实际 {result.status} err={result.error}"
        )
        assert result.cost_usd == 0.0, "桶满不计费"
        assert "bucket full" in (result.error or "").lower()
    finally:
        release(temp_tenant.tenant_id, "kling")


@pytest.mark.integration
def test_gateway_user_id_fallback_resolves_tenant(temp_user, pg_engine):
    """request 只带 user_id（没显式 tenant_id）时，gateway 在 run() 入口
    自动调 ``resolve_tenant_context(user_id)`` 兜底，仍正确做 acquire/release。

    验证步骤：
    - 跑一次成功调用（fake provider 总是 succeed）
    - tenant_id 是 ``u:{user_id}``（用户没建 workspace）
    - bucket 行已落库且 in_flight 归零（acquire 后 release）
    """
    from app.services.model_gateway.gateway import Gateway
    from app.services.model_gateway.types import (
        CallStatus,
        ModelAction,
        ProviderName,
        RenderRequest,
    )
    from app.services.pipeline.tenant import clear_cache, resolve_tenant_id

    clear_cache()  # 测试隔离：避免上一 case 留下的缓存项

    gw = Gateway()
    gw.register(_build_fake_provider(name_value="demo", action_value="llm"))
    gw._default_routing[ModelAction.LLM] = [ProviderName.DEMO]

    expected_tid = resolve_tenant_id(temp_user["id"])
    assert expected_tid == f"u:{temp_user['id']}", (
        f"users 表无 workspace 时应 fallback 到 u: 前缀；实际 {expected_tid}"
    )

    try:
        result = gw.run(
            RenderRequest(
                action=ModelAction.LLM,
                params={"messages": [{"role": "user", "content": "hi"}]},
                user_id=temp_user["id"],
                # 注意：故意不传 tenant_id / tenant_plan
            )
        )
        assert result.status == CallStatus.SUCCEEDED
        assert result.provider == ProviderName.DEMO

        # bucket 行已被 ensure_bucket 落库，且 release 后 in_flight=0
        with pg_engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT current_in_flight, max_concurrent "
                    "FROM provider_concurrency_buckets "
                    "WHERE tenant_id = :t AND provider_name = 'demo'"
                ),
                {"t": expected_tid},
            ).fetchone()
        assert row is not None, "user_id fallback 后应该 ensure 出 demo 桶"
        assert int(row[0]) == 0, "release 后 in_flight 应回 0"
        assert int(row[1]) > 0
    finally:
        # 清理 fallback 创建的桶（temp_user fixture 不知道这个 tenant_id）
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM provider_concurrency_buckets WHERE tenant_id = :t"
                ),
                {"t": expected_tid},
            )
            conn.execute(
                text("DELETE FROM tenant_quotas WHERE tenant_id = :t"),
                {"t": expected_tid},
            )
        clear_cache()
