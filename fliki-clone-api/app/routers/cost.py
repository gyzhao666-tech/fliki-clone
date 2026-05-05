"""Track-18 · 按 tenant 聚合的 cost 视图。

提供 2 个端点：

- ``GET /api/cost/summary``：返本期内（默认本月）该 tenant 的总成本 +
  按 provider 拆分。前端 4 格 stat 下方的「成本明细」横向 bar 用。
- ``GET /api/cost/recent``：返该 tenant 最近 N 条 model_calls，用于「今天有
  哪些调用」明细折叠。

设计取舍：

- **不复用 `/pipelines/quota`**：那个端点返 `tenant_quotas` 状态（reserved /
  monthly_limit / concurrent_max），是「容量」视图；本端点是「明细」视图，
  数据源不同（tenant_quotas vs model_calls 实际写入），分开避免一个端点
  混合两份数据。
- **不强制 admin**：当前 user 只能看自己 tenant_id 下的成本（默认从
  `resolve_tenant_id(user_id)` 推导）；想看任意 tenant 用 explicit
  ``?tenant_id=`` 参数（仅 admin 通过；非 admin 强制覆盖回自己的）。
- **不做时序聚合**（按天/按 provider × 时间矩阵）：v1 cost 视图不滚动，
  L-03 metric dashboard 才做时序；这里只返「截止此刻的本期累计 + 最近 N 条」。

Security：
- `?tenant_id=` 只允许两类调用方提供：
  1. 调用方本人的 tenant_id（被 resolver 推导出的） → 直通
  2. admin（邮箱白名单命中） → 直通
  其余情况强制覆盖回 user 自己的 tenant_id（不抛 403，避免破坏原本是 admin
  从前端抛参数的体验）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.deps import CurrentUser
from app.routers.admin_flags import _is_admin_email
from app.services.pipeline import tenant as pipeline_tenant


router = APIRouter(prefix="/cost", tags=["cost"])


# ── Pydantic 模型 ────────────────────────────────────────────────────────────


class ProviderCostRow(BaseModel):
    provider: str
    cost_usd: float
    call_count: int
    success_count: int
    failed_count: int


class CostSummaryOut(BaseModel):
    tenant_id: str = Field(..., description="实际查询的 tenant_id（可能被 server 重写为调用方自己的）")
    period: str = Field(..., description="`monthly`（本自然月）/ `weekly`（最近 7 天）/ `daily`（最近 24 小时）")
    period_start: datetime
    period_end: datetime
    total_cost_usd: float
    total_calls: int
    by_provider: list[ProviderCostRow]


class RecentCallOut(BaseModel):
    id: str
    user_id: Optional[str]
    file_id: Optional[str]
    provider: str
    model: Optional[str]
    action: str
    cost_usd: float
    duration_ms: int
    status: str
    error: Optional[str]
    created_at: datetime


class RecentCallsOut(BaseModel):
    tenant_id: str
    items: list[RecentCallOut]


# ── helpers ──────────────────────────────────────────────────────────────────


def _engine():
    return create_engine(get_settings().database_url_sync)


def _resolve_query_tenant(
    *,
    request_tenant_id: Optional[str],
    current_user: CurrentUser,
) -> str:
    """决定本次查询的 tenant_id（带 admin 白名单 + 兜底）。

    - 没传 ``tenant_id`` → 用 resolve_tenant_id(user_id)
    - 传了但与 user 自己的 tenant 不同 → 仅 admin 放行；否则覆盖回自己的（静默）
    """
    own = pipeline_tenant.resolve_tenant_id(current_user.id)
    if not request_tenant_id:
        return own
    if request_tenant_id == own:
        return own
    if _is_admin_email(current_user.email):
        return request_tenant_id
    return own


def _period_window(period: str) -> tuple[datetime, datetime, str]:
    """把 ``period`` 字符串展开为 (period_start, period_end, normalized_period)。

    - ``monthly``：本自然月 00:00:00 UTC → 现在
    - ``weekly``：现在 -7d → 现在
    - ``daily``：现在 -24h → 现在
    """
    now = datetime.now(timezone.utc)
    p = (period or "monthly").lower()
    if p == "weekly":
        start = now.replace(microsecond=0) - _timedelta(days=7)
        return start, now, "weekly"
    if p == "daily":
        start = now.replace(microsecond=0) - _timedelta(hours=24)
        return start, now, "daily"
    # monthly default
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now, "monthly"


def _timedelta(*, days: int = 0, hours: int = 0):
    """避免顶部 import 污染（仅本路由用）。"""
    from datetime import timedelta
    return timedelta(days=days, hours=hours)


# ── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/summary", response_model=CostSummaryOut)
async def cost_summary(
    current_user: CurrentUser,
    tenant_id: Optional[str] = Query(default=None, description="目标 tenant；不传 = 调用方自己的"),
    period: str = Query(default="monthly", description="monthly / weekly / daily"),
) -> CostSummaryOut:
    """按 tenant 聚合的成本视图（含 provider 拆分）。"""
    if period not in ("monthly", "weekly", "daily"):
        raise HTTPException(status_code=400, detail="period must be one of: monthly / weekly / daily")
    effective_tenant = _resolve_query_tenant(
        request_tenant_id=tenant_id, current_user=current_user
    )
    period_start, period_end, norm_period = _period_window(period)

    sql = text(
        """
        SELECT
            provider,
            COALESCE(SUM(cost_usd), 0)::float AS cost_usd,
            COUNT(*)::int AS call_count,
            SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END)::int AS success_count,
            SUM(CASE WHEN status NOT IN ('succeeded', 'rate_limited') THEN 1 ELSE 0 END)::int AS failed_count
          FROM model_calls
         WHERE tenant_id = :tenant_id
           AND created_at >= :period_start
           AND created_at <  :period_end
         GROUP BY provider
         ORDER BY cost_usd DESC
        """
    )

    by_provider: list[ProviderCostRow] = []
    total_cost = 0.0
    total_calls = 0
    try:
        engine = _engine()
        with engine.connect() as conn:
            for row in conn.execute(
                sql,
                {
                    "tenant_id": effective_tenant,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            ).mappings():
                by_provider.append(ProviderCostRow(**row))
                total_cost += float(row["cost_usd"] or 0)
                total_calls += int(row["call_count"] or 0)
    except Exception as exc:  # pragma: no cover - DB 故障让前端拿空集而不是 500
        raise HTTPException(status_code=503, detail=f"cost query failed: {exc}") from exc

    return CostSummaryOut(
        tenant_id=effective_tenant,
        period=norm_period,
        period_start=period_start,
        period_end=period_end,
        total_cost_usd=round(total_cost, 6),
        total_calls=total_calls,
        by_provider=by_provider,
    )


@router.get("/recent", response_model=RecentCallsOut)
async def cost_recent(
    current_user: CurrentUser,
    tenant_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> RecentCallsOut:
    """按 tenant 列最近 N 条 model_calls。"""
    effective_tenant = _resolve_query_tenant(
        request_tenant_id=tenant_id, current_user=current_user
    )

    sql = text(
        """
        SELECT id, user_id, file_id, provider, model, action,
               cost_usd, duration_ms, status, error, created_at
          FROM model_calls
         WHERE tenant_id = :tenant_id
         ORDER BY created_at DESC
         LIMIT :limit
        """
    )
    items: list[RecentCallOut] = []
    try:
        engine = _engine()
        with engine.connect() as conn:
            for row in conn.execute(
                sql,
                {"tenant_id": effective_tenant, "limit": int(limit)},
            ).mappings():
                items.append(RecentCallOut(**row))
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=f"cost recent query failed: {exc}") from exc

    return RecentCallsOut(tenant_id=effective_tenant, items=items)
