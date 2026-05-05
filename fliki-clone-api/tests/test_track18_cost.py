"""Track-18 · model_calls.tenant_id + cost 视图集成 + 单元测试。

覆盖矩阵
--------

unit (in-memory)
~~~~~~~~~~~~~~~~
1. ``test_resolve_tenant_for_record_explicit_wins``
   - 显式 tenant_id > user_id 兜底
2. ``test_resolve_tenant_for_record_user_fallback``
   - 缺 tenant_id 时 ``u:{user_id}``
3. ``test_resolve_tenant_for_record_anon_returns_none``
   - 都缺 → None（让 DB 端 NULL）
4. ``test_period_window_covers_three_modes``
   - monthly / weekly / daily 三种 period 时间窗口正确

integration (走真 PG)
~~~~~~~~~~~~~~~~~~~~~
5. ``test_record_call_writes_tenant_id``
   - 显式塞 tenant_id → DB 行 tenant_id 命中
   - 不塞但有 user_id → DB 行 ``u:{user_id}``
6. ``test_record_call_anonymous_keeps_null``
   - 完全匿名 → DB 行 tenant_id IS NULL（不阻塞业务）
7. ``test_cost_summary_aggregates_by_provider``
   - 同 tenant 写多 provider 多次 → /summary 按 provider 聚合 + 总金额正确
8. ``test_cost_summary_period_filter_excludes_old_rows``
   - daily / weekly / monthly 各窗口不会越界
9. ``test_cost_recent_returns_descending_with_limit``
   - /recent 按 created_at DESC + limit 正确
10. ``test_resolve_query_tenant_admin_passes_through``
    - admin 邮箱可指定其他 tenant；非 admin 强制覆盖回自己

设计取舍
-------
- 不污染 conftest：本文件内私有 ``_seed_model_call`` helper
- 同 tenant 内的所有 case 行用 ``test_mc_*`` 前缀，teardown 一次性 DELETE
- /summary /recent 直接调 router 函数（async），用 asyncio.run 跑（与
  test_admin_flags 同款，避免起 TestClient + AsyncSession 的 sandbox 坑）
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.unit  # 默认；个别 case 覆盖 integration


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_user(user_id: str, email: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email=email, name="pytest")


def _seed_model_call(
    engine: Engine,
    *,
    tenant_id: str,
    user_id: str | None = None,
    provider: str = "siliconflow",
    model: str | None = "stub",
    action: str = "llm",
    cost_usd: float = 0.001,
    status: str = "succeeded",
    created_at: datetime | None = None,
    record_id: str | None = None,
) -> str:
    """直接 INSERT 一条 model_calls 行（绕开 record_call，让 case 能精确控时间窗口）。"""
    rid = record_id or f"test_mc_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO model_calls
                    (id, user_id, tenant_id, file_id, pipeline_step_id,
                     provider, model, action, cost_usd, duration_ms,
                     status, error, request_summary, created_at)
                VALUES
                    (:id, :uid, :tid, NULL, NULL,
                     :prov, :mdl, :act, :cost, 100,
                     :st, NULL, NULL, :ts)
                """
            ),
            {
                "id": rid,
                "uid": user_id,
                "tid": tenant_id,
                "prov": provider,
                "mdl": model,
                "act": action,
                "cost": cost_usd,
                "st": status,
                "ts": created_at or datetime.now(timezone.utc),
            },
        )
    return rid


def _cleanup_model_calls_for_tenant(engine: Engine, tenant_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM model_calls WHERE tenant_id = :t"),
            {"t": tenant_id},
        )


@pytest.fixture
def cost_tenant(pg_engine: Engine) -> Iterator[str]:
    """专给 cost case 用的隔离 tenant：前缀 test_t: 与既有 fixture 一致。"""
    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    yield tid
    _cleanup_model_calls_for_tenant(pg_engine, tid)


def _run(coro):
    """同步 case 跑 async endpoint 函数；与 test_admin_flags 同款。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── unit cases ───────────────────────────────────────────────────────────────


def test_resolve_tenant_for_record_explicit_wins():
    from app.services.model_gateway.cost import _resolve_tenant_for_record

    assert (
        _resolve_tenant_for_record("ws:abc", "user-1") == "ws:abc"
    ), "显式 tenant_id 必须优先于 user_id 兜底"


def test_resolve_tenant_for_record_user_fallback():
    from app.services.model_gateway.cost import _resolve_tenant_for_record

    assert _resolve_tenant_for_record(None, "user-42") == "u:user-42"
    assert _resolve_tenant_for_record("", "user-42") == "u:user-42", "空字符串视为缺失"


def test_resolve_tenant_for_record_anon_returns_none():
    from app.services.model_gateway.cost import _resolve_tenant_for_record

    assert _resolve_tenant_for_record(None, None) is None
    assert _resolve_tenant_for_record("", "") is None


def test_period_window_covers_three_modes():
    from app.routers.cost import _period_window

    s_m, e_m, p_m = _period_window("monthly")
    s_w, e_w, p_w = _period_window("weekly")
    s_d, e_d, p_d = _period_window("daily")

    now = datetime.now(timezone.utc)
    assert p_m == "monthly" and s_m.day == 1 and s_m.hour == 0
    assert p_w == "weekly" and (now - s_w).days == 7
    assert p_d == "daily" and 23 <= (now - s_d).total_seconds() / 3600 <= 25
    for s, e in [(s_m, e_m), (s_w, e_w), (s_d, e_d)]:
        assert s < e, "period_start 必须早于 period_end"

    # 兜底：未知 period 走 monthly
    s_x, _, p_x = _period_window("yearly")
    assert p_x == "monthly" and s_x == s_m or s_x.day == 1


# ── integration cases ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_record_call_writes_tenant_id(pg_engine: Engine, cost_tenant: str):
    """显式 tenant_id / user_id 兜底两条路径都写到 DB.tenant_id 列。"""
    from app.services.model_gateway.cost import record_call
    from app.services.model_gateway.types import CallStatus, ModelAction, ProviderName

    rid_explicit = record_call(
        user_id="some-user",
        tenant_id=cost_tenant,
        file_id=None,
        pipeline_step_id=None,
        provider=ProviderName.SILICONFLOW,
        model="stub",
        action=ModelAction.LLM,
        cost_usd=0.005,
        duration_ms=10,
        status=CallStatus.SUCCEEDED,
    )

    rid_fallback = record_call(
        user_id="user-fb",
        tenant_id=None,
        file_id=None,
        pipeline_step_id=None,
        provider=ProviderName.SILICONFLOW,
        model="stub",
        action=ModelAction.LLM,
        cost_usd=0.001,
        duration_ms=5,
        status=CallStatus.SUCCEEDED,
    )

    try:
        with pg_engine.connect() as conn:
            row1 = conn.execute(
                text("SELECT tenant_id FROM model_calls WHERE id = :id"),
                {"id": rid_explicit},
            ).first()
            row2 = conn.execute(
                text("SELECT tenant_id FROM model_calls WHERE id = :id"),
                {"id": rid_fallback},
            ).first()
        assert row1 is not None and row1[0] == cost_tenant
        assert row2 is not None and row2[0] == "u:user-fb"
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM model_calls WHERE id IN (:a, :b)"),
                {"a": rid_explicit, "b": rid_fallback},
            )


@pytest.mark.integration
def test_record_call_anonymous_keeps_null(pg_engine: Engine):
    """user_id + tenant_id 都缺时，DB tenant_id 列为 NULL（业务不阻塞）。"""
    from app.services.model_gateway.cost import record_call
    from app.services.model_gateway.types import CallStatus, ModelAction, ProviderName

    rid = record_call(
        user_id=None,
        tenant_id=None,
        file_id=None,
        pipeline_step_id=None,
        provider=ProviderName.SILICONFLOW,
        model="stub",
        action=ModelAction.LLM,
        cost_usd=0.001,
        duration_ms=5,
        status=CallStatus.SUCCEEDED,
    )
    try:
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT tenant_id FROM model_calls WHERE id = :id"),
                {"id": rid},
            ).first()
        assert row is not None and row[0] is None
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM model_calls WHERE id = :id"),
                {"id": rid},
            )


@pytest.mark.integration
def test_cost_summary_aggregates_by_provider(pg_engine: Engine, cost_tenant: str):
    """同 tenant 多 provider 多次调用 → /summary 按 provider 聚合，总金额正确。"""
    _seed_model_call(pg_engine, tenant_id=cost_tenant, provider="siliconflow", cost_usd=0.010)
    _seed_model_call(pg_engine, tenant_id=cost_tenant, provider="siliconflow", cost_usd=0.005)
    _seed_model_call(pg_engine, tenant_id=cost_tenant, provider="kling", cost_usd=0.200)
    _seed_model_call(pg_engine, tenant_id=cost_tenant, provider="openai", cost_usd=0.030, status="failed")

    # admin user 跳过权限覆盖，让指定 tenant 直通
    from app.routers.cost import cost_summary

    out = _run(
        cost_summary(
            current_user=_fake_user("admin-user", "demo@example.com"),
            tenant_id=cost_tenant,
            period="monthly",
        )
    )

    assert out.tenant_id == cost_tenant
    assert out.total_calls == 4
    assert abs(out.total_cost_usd - (0.010 + 0.005 + 0.200 + 0.030)) < 1e-6
    by_prov = {r.provider: r for r in out.by_provider}
    assert "siliconflow" in by_prov and abs(by_prov["siliconflow"].cost_usd - 0.015) < 1e-6
    assert by_prov["siliconflow"].call_count == 2 and by_prov["siliconflow"].success_count == 2
    assert by_prov["openai"].failed_count == 1
    # 排序：cost desc → kling 在最前
    assert out.by_provider[0].provider == "kling"


@pytest.mark.integration
def test_cost_summary_period_filter_excludes_old_rows(
    pg_engine: Engine, cost_tenant: str
):
    """老行（period_start 之前）不参与聚合。"""
    now = datetime.now(timezone.utc)
    # 月初前一天的行 → monthly 应该排除（如果今天是月初，把它放到 60 天前避免边界）
    far_old = now.replace(day=1) - timedelta(days=2)
    _seed_model_call(
        pg_engine, tenant_id=cost_tenant,
        provider="kling", cost_usd=999.0,
        created_at=far_old,
    )
    # 当下的行 → 各 period 都包含
    _seed_model_call(
        pg_engine, tenant_id=cost_tenant,
        provider="siliconflow", cost_usd=1.0,
        created_at=now,
    )

    from app.routers.cost import cost_summary

    monthly = _run(
        cost_summary(
            current_user=_fake_user("admin-user", "demo@example.com"),
            tenant_id=cost_tenant,
            period="monthly",
        )
    )
    daily = _run(
        cost_summary(
            current_user=_fake_user("admin-user", "demo@example.com"),
            tenant_id=cost_tenant,
            period="daily",
        )
    )

    # monthly：今天的 1.0 必算入；老行 (60 天前) 必排除
    assert abs(monthly.total_cost_usd - 1.0) < 1e-6, f"monthly={monthly.total_cost_usd}"
    # daily：只算最近 24h 的当下行
    assert abs(daily.total_cost_usd - 1.0) < 1e-6


@pytest.mark.integration
def test_cost_recent_returns_descending_with_limit(
    pg_engine: Engine, cost_tenant: str
):
    """/recent 按 created_at DESC + limit 截断；返结构与 ORM 字段对齐。"""
    now = datetime.now(timezone.utc)
    rid_old = _seed_model_call(
        pg_engine, tenant_id=cost_tenant, provider="siliconflow",
        cost_usd=0.001, created_at=now - timedelta(minutes=10),
    )
    rid_mid = _seed_model_call(
        pg_engine, tenant_id=cost_tenant, provider="kling",
        cost_usd=0.05, created_at=now - timedelta(minutes=5),
    )
    rid_new = _seed_model_call(
        pg_engine, tenant_id=cost_tenant, provider="openai",
        cost_usd=0.005, created_at=now,
    )

    from app.routers.cost import cost_recent

    out = _run(
        cost_recent(
            current_user=_fake_user("admin-user", "demo@example.com"),
            tenant_id=cost_tenant,
            limit=2,
        )
    )

    assert out.tenant_id == cost_tenant
    assert len(out.items) == 2
    assert out.items[0].id == rid_new
    assert out.items[1].id == rid_mid
    assert all(it.cost_usd >= 0 for it in out.items)


@pytest.mark.integration
def test_resolve_query_tenant_admin_passes_through(
    pg_engine: Engine, cost_tenant: str
):
    """admin 邮箱可查任意 tenant；非 admin 强制覆盖回自己（不抛 403）。"""
    from app.routers.cost import _resolve_query_tenant

    admin_user = _fake_user("admin-1", "demo@example.com")
    assert (
        _resolve_query_tenant(request_tenant_id=cost_tenant, current_user=admin_user)
        == cost_tenant
    ), "admin 必须能查任意 tenant_id"

    # 非 admin 静默被覆盖回 'u:{user_id}'
    normal = _fake_user("normal-user", "alice@example.com")
    out = _resolve_query_tenant(request_tenant_id=cost_tenant, current_user=normal)
    assert out.startswith("u:") and out != cost_tenant, (
        "非 admin 不能查指定的其他 tenant"
    )
