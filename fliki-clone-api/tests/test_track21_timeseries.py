"""Track-21 · /api/cost/timeseries 时序聚合集成 + 单元测试。

覆盖矩阵
--------

unit (in-memory)
~~~~~~~~~~~~~~~~
1. ``test_resolve_bucket_whitelist``
   - daily → 'day' / weekly → 'week' / 未知 → 'day'（兜底）
2. ``test_clamp_days_boundaries``
   - 负数 / 0 → 1；超大 → 365；中间值原样

integration (走真 PG)
~~~~~~~~~~~~~~~~~~~~~
3. ``test_timeseries_groups_by_day_and_provider``
   - 同 tenant 跨 7 天写多 provider 行 → daily 桶聚合每天 N 条 / provider
4. ``test_timeseries_provider_filter_excludes_others``
   - 单 provider filter 仅返该 provider 的桶
5. ``test_timeseries_empty_returns_empty_items``
   - 不存在的 tenant → items 空数组（不返 404）
6. ``test_timeseries_excludes_rows_outside_window``
   - days=7 窗口外的老行不参与聚合
7. ``test_timeseries_admin_passes_through_other_tenant``
   - admin 邮箱可指定他人 tenant；非 admin 静默覆盖回自己（与 /summary /recent 一致）
8. ``test_timeseries_weekly_period_uses_week_truncate``
   - weekly 桶把同周 N 行折成同一行（DATE_TRUNC('week') 行为）

设计取舍
-------
- 与 test_track18_cost.py 同款：本文件内私有 ``_seed_model_call`` helper，不污染
  conftest（共享数据库 fixture ``pg_engine`` / ``cost_tenant`` 风格但本文件内独立 fixture）
- async endpoint 用 ``asyncio.run`` 直接跑（与 test_admin_flags / test_track18_cost
  同款，避开 sandbox 起 TestClient 的坑）
- 隔离 tenant 前缀 ``test_t21:`` 与 T-18 / 业务命名空间互斥；teardown 一次性 DELETE
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_user(user_id: str, email: str) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, email=email, name="pytest")


def _seed_model_call(
    engine: Engine,
    *,
    tenant_id: str,
    provider: str = "siliconflow",
    cost_usd: float = 0.001,
    status: str = "succeeded",
    created_at: datetime | None = None,
    record_id: str | None = None,
) -> str:
    rid = record_id or f"test_t21_mc_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO model_calls
                    (id, user_id, tenant_id, file_id, pipeline_step_id,
                     provider, model, action, cost_usd, duration_ms,
                     status, error, request_summary, created_at)
                VALUES
                    (:id, NULL, :tid, NULL, NULL,
                     :prov, 'stub', 'llm', :cost, 100,
                     :st, NULL, NULL, :ts)
                """
            ),
            {
                "id": rid,
                "tid": tenant_id,
                "prov": provider,
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
def t21_tenant(pg_engine: Engine) -> Iterator[str]:
    """Track-21 专用隔离 tenant，前缀 ``test_t21:`` 与 T-18 ``test_t:`` 互斥。"""
    tid = f"test_t21:{uuid.uuid4().hex[:12]}"
    yield tid
    _cleanup_model_calls_for_tenant(pg_engine, tid)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── unit cases ───────────────────────────────────────────────────────────────


def test_resolve_bucket_whitelist():
    from app.routers.cost import _resolve_bucket

    assert _resolve_bucket("daily") == "day"
    assert _resolve_bucket("DAILY") == "day"  # 大写也通
    assert _resolve_bucket("weekly") == "week"
    assert _resolve_bucket("yearly") == "day", "未知 period 必须兜底为 day"
    assert _resolve_bucket("") == "day"
    assert _resolve_bucket(None) == "day"  # type: ignore[arg-type]


def test_clamp_days_boundaries():
    from app.routers.cost import _clamp_days

    assert _clamp_days(0) == 1
    assert _clamp_days(-5) == 1
    assert _clamp_days(30) == 30
    assert _clamp_days(365) == 365
    assert _clamp_days(99999) == 365
    assert _clamp_days("7") == 7  # type: ignore[arg-type]
    assert _clamp_days("abc") == 30, "解析失败兜底回 30"  # type: ignore[arg-type]


# ── integration cases ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_timeseries_groups_by_day_and_provider(
    pg_engine: Engine, t21_tenant: str
):
    """7 天每天 2 provider 各 1 行 → /timeseries 应返 14 行（按 (day, provider) 拆）。"""
    now = datetime.now(timezone.utc)
    # 跨 7 天，每天 siliconflow + kling 各一行
    for d in range(7):
        ts = now - timedelta(days=d, hours=2)  # -2h 避开 day 边界
        _seed_model_call(
            pg_engine, tenant_id=t21_tenant,
            provider="siliconflow", cost_usd=0.01, created_at=ts,
        )
        _seed_model_call(
            pg_engine, tenant_id=t21_tenant,
            provider="kling", cost_usd=0.20, created_at=ts,
        )

    from app.routers.cost import cost_timeseries

    out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=t21_tenant,
            provider=None,
            period="daily",
            days=10,
        )
    )

    assert out.tenant_id == t21_tenant
    assert out.period == "daily"
    assert out.days == 10
    assert out.provider_filter is None
    # 7 天 × 2 provider = 14 个聚合点（每天每 provider 一条）
    assert len(out.items) == 14, f"items={len(out.items)}"
    # 总和验证：siliconflow 7×0.01 + kling 7×0.20 = 0.07 + 1.40 = 1.47
    assert abs(out.total_cost_usd - 1.47) < 1e-6, f"total={out.total_cost_usd}"
    assert out.total_calls == 14
    # 排序：date asc, provider asc
    for i in range(len(out.items) - 1):
        a, b = out.items[i], out.items[i + 1]
        assert (a.date, a.provider) <= (b.date, b.provider), "结果必须按 (date, provider) ASC"


@pytest.mark.integration
def test_timeseries_provider_filter_excludes_others(
    pg_engine: Engine, t21_tenant: str
):
    """?provider=kling 仅返 kling 的桶；其它 provider 全过滤。"""
    now = datetime.now(timezone.utc)
    _seed_model_call(pg_engine, tenant_id=t21_tenant, provider="siliconflow", cost_usd=0.50, created_at=now)
    _seed_model_call(pg_engine, tenant_id=t21_tenant, provider="kling", cost_usd=0.10, created_at=now)
    _seed_model_call(pg_engine, tenant_id=t21_tenant, provider="kling", cost_usd=0.20, created_at=now - timedelta(days=1, hours=2))

    from app.routers.cost import cost_timeseries

    out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=t21_tenant,
            provider="kling",
            period="daily",
            days=7,
        )
    )

    assert out.provider_filter == "kling"
    assert all(it.provider == "kling" for it in out.items), "filter 必须排除其它 provider"
    assert abs(out.total_cost_usd - 0.30) < 1e-6, "0.10 + 0.20"
    assert out.total_calls == 2


@pytest.mark.integration
def test_timeseries_empty_returns_empty_items(pg_engine: Engine):
    """不存在的 tenant → items=[]，不抛 404。"""
    from app.routers.cost import cost_timeseries

    nonexistent = f"test_t21:nonexistent_{uuid.uuid4().hex[:8]}"
    out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=nonexistent,
            provider=None,
            period="daily",
            days=30,
        )
    )

    assert out.tenant_id == nonexistent
    assert out.items == []
    assert out.total_cost_usd == 0.0
    assert out.total_calls == 0
    # 时间窗口字段仍正常返
    assert out.period_start < out.period_end


@pytest.mark.integration
def test_timeseries_excludes_rows_outside_window(
    pg_engine: Engine, t21_tenant: str
):
    """days=7 窗口外的老行不计入。"""
    now = datetime.now(timezone.utc)
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="kling",
        cost_usd=999.0, created_at=now - timedelta(days=30),
    )
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="siliconflow",
        cost_usd=1.0, created_at=now - timedelta(hours=2),
    )

    from app.routers.cost import cost_timeseries

    out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=t21_tenant,
            provider=None,
            period="daily",
            days=7,
        )
    )

    assert out.total_cost_usd == pytest.approx(1.0, abs=1e-6), (
        f"30 天前 999 行应被排除；total={out.total_cost_usd}"
    )
    assert out.total_calls == 1
    assert all(it.provider == "siliconflow" for it in out.items)


@pytest.mark.integration
def test_timeseries_admin_passes_through_other_tenant(
    pg_engine: Engine, t21_tenant: str
):
    """admin 邮箱可查任意 tenant；非 admin 静默被覆盖回自己（不抛 403）。"""
    _seed_model_call(pg_engine, tenant_id=t21_tenant, provider="kling", cost_usd=0.5)

    from app.routers.cost import cost_timeseries

    # admin 直通
    admin_out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=t21_tenant,
            provider=None,
            period="daily",
            days=7,
        )
    )
    assert admin_out.tenant_id == t21_tenant
    assert admin_out.total_calls == 1

    # 非 admin 被覆盖回 'u:{user_id}'
    normal_out = _run(
        cost_timeseries(
            current_user=_fake_user("normal-user", "alice@example.com"),
            tenant_id=t21_tenant,
            provider=None,
            period="daily",
            days=7,
        )
    )
    assert normal_out.tenant_id != t21_tenant
    assert normal_out.tenant_id.startswith("u:"), f"tenant_id={normal_out.tenant_id}"
    # 覆盖回 normal-user 自己的 tenant，那个 tenant 没有种 model_calls 行 → 空
    assert normal_out.total_calls == 0


@pytest.mark.integration
def test_timeseries_weekly_period_uses_week_truncate(
    pg_engine: Engine, t21_tenant: str
):
    """weekly 桶 DATE_TRUNC('week') 把同周多行折成同 (week, provider) 一行。

    PG DATE_TRUNC('week', x) 把周一作为周首；同一自然周的 N 行必折同一桶。
    """
    now = datetime.now(timezone.utc)
    # 当周内 3 行 + 上周 1 行；都同 provider
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="kling",
        cost_usd=0.10, created_at=now - timedelta(hours=2),
    )
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="kling",
        cost_usd=0.20, created_at=now - timedelta(hours=8),
    )
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="kling",
        cost_usd=0.30, created_at=now - timedelta(hours=24),
    )
    _seed_model_call(
        pg_engine, tenant_id=t21_tenant, provider="kling",
        cost_usd=0.40, created_at=now - timedelta(days=8),
    )

    from app.routers.cost import cost_timeseries

    out = _run(
        cost_timeseries(
            current_user=_fake_user("admin-1", "demo@example.com"),
            tenant_id=t21_tenant,
            provider=None,
            period="weekly",
            days=14,
        )
    )

    assert out.period == "weekly"
    # 4 行属于至多 2 个不同的「周」桶；同 provider → 1 ~ 2 个聚合点
    assert 1 <= len(out.items) <= 2, f"items={len(out.items)}"
    assert out.total_calls == 4
    assert abs(out.total_cost_usd - 1.0) < 1e-6  # 0.10 + 0.20 + 0.30 + 0.40
    # 验证至少有一个桶 cost > 0.5（说明聚合了 3 行 0.10+0.20+0.30=0.60）
    assert any(it.cost_usd >= 0.59 for it in out.items), (
        "应有一个周桶聚合了当周 3 行：0.10+0.20+0.30 = 0.60"
    )
