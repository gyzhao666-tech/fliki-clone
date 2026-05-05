"""模型调用配额：预扣 / 退还 / 查询。

并发模型：行级 SELECT ... FOR UPDATE（PG）保证同一 user/tenant 多个并发启动请求互斥；
SQLite / 测试环境降级到普通 SELECT，因为 fliki 主仓走 PG。

v1（user 级，兼容）API：
- `get_or_create(user_id) -> QuotaSnapshot`：拉额度，没行就用默认值 INSERT
- `reserve(user_id, amount) -> ReserveResult`：尝试预扣；失败时返回 reason
- `release(user_id, amount)`：退还
- `count_active_runs(user_id) -> int`：当前活跃 run 数

v2（tenant 级，新路径）API：
- `get_or_create_tenant(tenant_id, *, plan, display_name) -> TenantQuotaSnapshot`
- `reserve_tenant(tenant_id, amount) -> ReserveResult`
- `release_tenant(tenant_id, amount)`
- `count_active_runs_tenant(tenant_id) -> int`

设计取舍：
- 不引 ORM session：所有查询走 sync engine（与 runner.py 一致），让 Celery worker / BackgroundTask
  / async router 都能调
- `current_period_start` 当跨月时由本模块手动 reset：调 `get_or_create*` 时检查是否需要 rollover
- v1 与 v2 互不耦合，迁移期可并存；router 已切到 v2，runner 退还也走 v2
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── 公共数据类 ────────────────────────────────────────────────────────────────


@dataclass
class QuotaSnapshot:
    user_id: str
    monthly_limit_usd: float
    current_period_usage_usd: float
    current_period_start: datetime
    concurrent_max: int

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.monthly_limit_usd - self.current_period_usage_usd)


@dataclass
class ReserveResult:
    ok: bool
    reason: Optional[str] = None
    snapshot: Optional[QuotaSnapshot] = None
    tenant_snapshot: Optional["TenantQuotaSnapshot"] = None


@dataclass
class TenantQuotaSnapshot:
    tenant_id: str
    plan: str
    monthly_limit_usd: float
    current_period_usage_usd: float
    current_period_start: datetime
    concurrent_max: int
    display_name: Optional[str] = None

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.monthly_limit_usd - self.current_period_usage_usd)


# ── 入口 API ──────────────────────────────────────────────────────────────────


def _engine():
    return create_engine(get_settings().database_url_sync)


def get_or_create(user_id: str) -> QuotaSnapshot:
    """读取 user 的额度行；不存在则用默认值 INSERT。
    每次调用顺便检查是否要按月 rollover。
    """

    if not user_id:
        # 匿名用户给一个临时上限，与系统默认对齐；不会落库
        return QuotaSnapshot(
            user_id="",
            monthly_limit_usd=10.0,
            current_period_usage_usd=0.0,
            current_period_start=_period_start_for(_now()),
            concurrent_max=2,
        )

    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT user_id, monthly_limit_usd, current_period_usage_usd,
                       current_period_start, concurrent_max
                  FROM model_quotas WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        ).fetchone()

        if not row:
            new_id = str(uuid.uuid4())
            now = _now()
            conn.execute(
                text(
                    """
                    INSERT INTO model_quotas
                        (id, user_id, monthly_limit_usd, current_period_usage_usd,
                         current_period_start, concurrent_max, created_at, updated_at)
                    VALUES
                        (:id, :uid, 10.0, 0, :start, 2, NOW(), NOW())
                    """
                ),
                {"id": new_id, "uid": user_id, "start": now},
            )
            return QuotaSnapshot(
                user_id=user_id,
                monthly_limit_usd=10.0,
                current_period_usage_usd=0.0,
                current_period_start=now,
                concurrent_max=2,
            )

        snap = QuotaSnapshot(
            user_id=row[0],
            monthly_limit_usd=float(row[1]),
            current_period_usage_usd=float(row[2]),
            current_period_start=row[3],
            concurrent_max=int(row[4]),
        )

        # 检查是否要按月 rollover
        expected_start = _period_start_for(_now())
        if snap.current_period_start.replace(tzinfo=timezone.utc) < expected_start:
            conn.execute(
                text(
                    """
                    UPDATE model_quotas
                       SET current_period_usage_usd = 0,
                           current_period_start = :start,
                           updated_at = NOW()
                     WHERE user_id = :uid
                    """
                ),
                {"uid": user_id, "start": expected_start},
            )
            snap.current_period_usage_usd = 0.0
            snap.current_period_start = expected_start

        return snap


def reserve(user_id: str, amount: float) -> ReserveResult:
    """尝试预扣 `amount` USD；失败时返回 reason 不修改 DB。
    匿名用户（user_id 为空）直接放行（不写库）。
    """

    if amount < 0:
        return ReserveResult(ok=False, reason="amount must be non-negative")
    if not user_id:
        return ReserveResult(ok=True, snapshot=get_or_create(""))

    snap = get_or_create(user_id)  # 顺便 rollover
    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT monthly_limit_usd, current_period_usage_usd
                  FROM model_quotas WHERE user_id = :uid FOR UPDATE
                """
            ),
            {"uid": user_id},
        ).fetchone()
        if not row:  # 极端情况：被并发删除
            return ReserveResult(ok=False, reason="quota row missing after get_or_create")

        limit = float(row[0])
        usage = float(row[1])
        if usage + amount > limit + 1e-6:
            return ReserveResult(
                ok=False,
                reason=(
                    f"insufficient quota: need ${amount:.4f}, "
                    f"used ${usage:.4f}/${limit:.2f}"
                ),
                snapshot=snap,
            )

        conn.execute(
            text(
                """
                UPDATE model_quotas
                   SET current_period_usage_usd = current_period_usage_usd + :amt,
                       updated_at = NOW()
                 WHERE user_id = :uid
                """
            ),
            {"uid": user_id, "amt": float(amount)},
        )

    new_snap = QuotaSnapshot(
        user_id=user_id,
        monthly_limit_usd=snap.monthly_limit_usd,
        current_period_usage_usd=snap.current_period_usage_usd + amount,
        current_period_start=snap.current_period_start,
        concurrent_max=snap.concurrent_max,
    )
    return ReserveResult(ok=True, snapshot=new_snap)


def release(user_id: str, amount: float) -> None:
    """退还 amount USD（用于终态结算 reserved - actual 的差）。
    `amount <= 0` 跳过（实际花费 >= 预扣时不需要退）。
    """

    if not user_id or amount <= 1e-6:
        return
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE model_quotas
                   SET current_period_usage_usd =
                       GREATEST(0, current_period_usage_usd - :amt),
                       updated_at = NOW()
                 WHERE user_id = :uid
                """
            ),
            {"uid": user_id, "amt": float(amount)},
        )


def count_active_runs(user_id: str) -> int:
    """活跃 = 还没进入终态（succeeded / failed / cancelled）的 run 数。"""

    if not user_id:
        return 0
    engine = _engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM pipeline_runs
                 WHERE user_id = :uid
                   AND state NOT IN ('succeeded','failed','cancelled')
                """
            ),
            {"uid": user_id},
        ).fetchone()
        return int(row[0] or 0) if row else 0


# ── v2: tenant 级 API ────────────────────────────────────────────────────────
# 与 v1 几乎对称，只是主键换成 tenant_id；多了 plan / display_name。
# router 与 runner 终态退还都已切到 v2；v1 仅保留作向后兼容（老脚本/老 router 调用）。


def get_or_create_tenant(
    tenant_id: str,
    *,
    plan: str = "free",
    display_name: Optional[str] = None,
) -> TenantQuotaSnapshot:
    """读取 tenant 配额行；不存在则按 plan 默认值 INSERT。每次顺便 rollover。

    匿名 tenant_id（包含 `anon:`）拿一份「不落库」snapshot，避免 dev 测试污染表。
    """
    if not tenant_id:
        raise ValueError("tenant_id required")
    if tenant_id.startswith("anon:"):
        return TenantQuotaSnapshot(
            tenant_id=tenant_id,
            plan="free",
            monthly_limit_usd=10.0,
            current_period_usage_usd=0.0,
            current_period_start=_period_start_for(_now()),
            concurrent_max=2,
            display_name=display_name or "(anonymous)",
        )

    # 局部 import 避免 quota.py 顶层依赖 tenant.py（quota 更底层）
    from .tenant import plan_defaults

    defaults = plan_defaults(plan)
    monthly_default = float(defaults["monthly_limit_usd"])
    concurrent_default = int(defaults["concurrent_max"])

    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT tenant_id, display_name, plan, monthly_limit_usd,
                       current_period_usage_usd, current_period_start, concurrent_max
                  FROM tenant_quotas WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        ).fetchone()

        if not row:
            now = _now()
            conn.execute(
                text(
                    """
                    INSERT INTO tenant_quotas
                        (tenant_id, display_name, plan,
                         monthly_limit_usd, current_period_usage_usd,
                         current_period_start, concurrent_max,
                         created_at, updated_at)
                    VALUES
                        (:tid, :dn, :plan, :limit, 0, :start, :cmax, NOW(), NOW())
                    """
                ),
                {
                    "tid": tenant_id,
                    "dn": display_name,
                    "plan": plan,
                    "limit": monthly_default,
                    "start": now,
                    "cmax": concurrent_default,
                },
            )
            return TenantQuotaSnapshot(
                tenant_id=tenant_id,
                plan=plan,
                monthly_limit_usd=monthly_default,
                current_period_usage_usd=0.0,
                current_period_start=now,
                concurrent_max=concurrent_default,
                display_name=display_name,
            )

        snap = TenantQuotaSnapshot(
            tenant_id=row[0],
            display_name=row[1],
            plan=row[2],
            monthly_limit_usd=float(row[3]),
            current_period_usage_usd=float(row[4]),
            current_period_start=row[5],
            concurrent_max=int(row[6]),
        )

        # 跨月 rollover
        expected_start = _period_start_for(_now())
        if snap.current_period_start.replace(tzinfo=timezone.utc) < expected_start:
            conn.execute(
                text(
                    """
                    UPDATE tenant_quotas
                       SET current_period_usage_usd = 0,
                           current_period_start = :start,
                           updated_at = NOW()
                     WHERE tenant_id = :tid
                    """
                ),
                {"tid": tenant_id, "start": expected_start},
            )
            snap.current_period_usage_usd = 0.0
            snap.current_period_start = expected_start

        # display_name 来自 caller 的最新值（user.email / workspace.name）覆盖
        if display_name and display_name != snap.display_name:
            conn.execute(
                text(
                    "UPDATE tenant_quotas SET display_name=:dn, updated_at=NOW() WHERE tenant_id=:tid"
                ),
                {"tid": tenant_id, "dn": display_name},
            )
            snap.display_name = display_name

        return snap


def reserve_tenant(
    tenant_id: str,
    amount: float,
    *,
    plan: str = "free",
    display_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> ReserveResult:
    """tenant 级 reserve。匿名 tenant 直接放行不落库。

    Track-25：超限时（router 即将 raise 402）先在 `user:{user_id}` 频道推一条
    `quota_exceeded` 事件，让前端 layout.tsx 全局 hook 在 toast 上即时反馈
    「月度额度不足」，避免用户对着 402 错误页面发懵。`user_id` 缺省 None 时
    保留向后兼容（旧调用方 / 老脚本不会被打断）。
    """
    if amount < 0:
        return ReserveResult(ok=False, reason="amount must be non-negative")
    snap = get_or_create_tenant(tenant_id, plan=plan, display_name=display_name)
    if tenant_id.startswith("anon:"):
        return ReserveResult(ok=True, tenant_snapshot=snap)

    engine = _engine()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT monthly_limit_usd, current_period_usage_usd
                  FROM tenant_quotas WHERE tenant_id = :tid FOR UPDATE
                """
            ),
            {"tid": tenant_id},
        ).fetchone()
        if not row:  # pragma: no cover - get_or_create 刚 INSERT
            return ReserveResult(ok=False, reason="tenant_quotas row missing after upsert")

        limit = float(row[0])
        usage = float(row[1])
        if usage + amount > limit + 1e-6:
            # Track-25：抛 402 之前推 user-level 事件，让前端立即看到 toast
            if user_id:
                try:
                    from . import events as pipeline_events

                    pipeline_events.publish_user_event(
                        user_id,
                        "quota_exceeded",
                        {
                            "tenant_id": tenant_id,
                            "kind": "monthly_quota",
                            "message": (
                                f"月度额度不足：需要 ${amount:.4f}，已用 ${usage:.4f}/"
                                f"${limit:.2f}"
                            ),
                            "attempted_cost": float(amount),
                            "monthly_limit": float(limit),
                            "current_usage": float(usage),
                        },
                    )
                except Exception:  # pragma: no cover - publish 失败不阻断 quota 主流程
                    logger.warning(
                        "publish_user_event quota_exceeded failed user=%s tenant=%s",
                        user_id,
                        tenant_id,
                    )
            return ReserveResult(
                ok=False,
                reason=(
                    f"insufficient tenant quota ({tenant_id}): need ${amount:.4f}, "
                    f"used ${usage:.4f}/${limit:.2f}"
                ),
                tenant_snapshot=snap,
            )

        conn.execute(
            text(
                """
                UPDATE tenant_quotas
                   SET current_period_usage_usd = current_period_usage_usd + :amt,
                       updated_at = NOW()
                 WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id, "amt": float(amount)},
        )

    new_snap = TenantQuotaSnapshot(
        tenant_id=tenant_id,
        plan=snap.plan,
        monthly_limit_usd=snap.monthly_limit_usd,
        current_period_usage_usd=snap.current_period_usage_usd + amount,
        current_period_start=snap.current_period_start,
        concurrent_max=snap.concurrent_max,
        display_name=snap.display_name,
    )
    return ReserveResult(ok=True, tenant_snapshot=new_snap)


def release_tenant(tenant_id: str, amount: float) -> None:
    """退还 tenant 级 amount USD（用于终态结算 / cancel）。"""
    if not tenant_id or tenant_id.startswith("anon:") or amount <= 1e-6:
        return
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE tenant_quotas
                   SET current_period_usage_usd =
                       GREATEST(0, current_period_usage_usd - :amt),
                       updated_at = NOW()
                 WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id, "amt": float(amount)},
        )


def count_active_runs_tenant(tenant_id: str) -> int:
    """活跃 = 没进入终态的 run 数（按 pipeline_runs.tenant_id）。

    匿名（anon:）tenant 共享一个桶，仍按列名一起 count；调用方应自行决定
    要不要给匿名放行（router 当前给匿名放行）。
    """
    if not tenant_id:
        return 0
    engine = _engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM pipeline_runs
                 WHERE tenant_id = :tid
                   AND state NOT IN ('succeeded','failed','cancelled')
                """
            ),
            {"tid": tenant_id},
        ).fetchone()
        return int(row[0] or 0) if row else 0


def update_tenant_plan(
    tenant_id: str,
    new_plan: str,
    *,
    display_name: Optional[str] = None,
) -> TenantQuotaSnapshot:
    """订阅升级 / 续费 / 降级 时把 tenant 的 plan 切换到 new_plan，并按需 bump 桶。

    Track-11 用：Stripe webhook 收到 checkout.session.completed /
    customer.subscription.updated 后调一次。

    语义（升级安全 / 降级保护已手调过的桶）：
    1. tenant_quotas.plan = new_plan（无条件覆盖；plan 列就是「当前订阅档」的事实）
    2. monthly_limit_usd / concurrent_max：按 PLAN_DEFAULTS 取**新 plan 默认值**；
       但只在 `desired > current` 时上调（升级 bump），降级时**保留**当前值
       —— 用户可能花钱续 standard 后人手把月额改高了，降回 free 不应该突然砍掉
    3. provider_concurrency_buckets：遍历该 tenant 已存在的桶，调
       `provider_buckets.ensure_bucket(plan=new_plan)`；同样升级 bump、降级保留

    匿名 tenant（anon:）/ 不存在的 tenant 直接 `get_or_create_tenant` 兜底，避免
    webhook 落到一个还没初始化的租户身上。

    返回最新的 TenantQuotaSnapshot；调用方可写日志 / 返给前端展示。
    """
    if not tenant_id:
        raise ValueError("tenant_id required")

    # 局部 import 避免循环：tenant.py 依赖 quota.py，provider_buckets 也依赖 quota
    from .tenant import plan_defaults
    from . import provider_buckets

    snap = get_or_create_tenant(tenant_id, plan=new_plan, display_name=display_name)

    if tenant_id.startswith("anon:"):
        snap.plan = new_plan
        return snap

    defaults = plan_defaults(new_plan)
    desired_limit = float(defaults["monthly_limit_usd"])
    desired_concurrent = int(defaults["concurrent_max"])

    new_limit = max(desired_limit, snap.monthly_limit_usd)
    new_concurrent = max(desired_concurrent, snap.concurrent_max)

    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE tenant_quotas
                   SET plan = :plan,
                       monthly_limit_usd = :limit,
                       concurrent_max = :cmax,
                       updated_at = NOW()
                 WHERE tenant_id = :tid
                """
            ),
            {
                "tid": tenant_id,
                "plan": new_plan,
                "limit": new_limit,
                "cmax": new_concurrent,
            },
        )

        rows = conn.execute(
            text(
                "SELECT provider_name FROM provider_concurrency_buckets WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        ).fetchall()
        existing_providers = [r[0] for r in rows]

    for provider_name in existing_providers:
        try:
            provider_buckets.ensure_bucket(tenant_id, provider_name, plan=new_plan)
        except Exception:  # pragma: no cover
            logger.exception(
                "ensure_bucket bump failed tenant=%s provider=%s plan=%s",
                tenant_id,
                provider_name,
                new_plan,
            )

    logger.info(
        "tenant plan updated tenant=%s plan=%s monthly_limit_usd=%s concurrent_max=%s buckets_bumped=%d",
        tenant_id,
        new_plan,
        new_limit,
        new_concurrent,
        len(existing_providers),
    )

    return TenantQuotaSnapshot(
        tenant_id=tenant_id,
        plan=new_plan,
        monthly_limit_usd=new_limit,
        current_period_usage_usd=snap.current_period_usage_usd,
        current_period_start=snap.current_period_start,
        concurrent_max=new_concurrent,
        display_name=display_name or snap.display_name,
    )


# ── helpers ──────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _period_start_for(when: datetime) -> datetime:
    """当前自然月的第一天 UTC 00:00。"""
    return datetime(when.year, when.month, 1, tzinfo=timezone.utc)
