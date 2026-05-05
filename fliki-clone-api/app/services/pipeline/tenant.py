"""tenant 解析 + plan 默认派生（配额 v2）。

v2 把配额、并发、provider 槽位的「主体」从 user 升级为 tenant。
tenant 的来源（按优先级）：
1. user 拥有的第一个 workspace（`workspaces.owner_id == user_id`）→ `ws:{workspace.id}`
2. 兜底：`u:{user_id}`

不读 `team_members`：v1 还没建立「user 同时属于多 workspace」的活跃 workspace 概念，
team member 关系暂作为协作权限模型，不影响计费桶。

为什么不直接用 user.id：
- 一个 workspace 内多个 user 共享月度额度 + 并发上限（团队套餐）
- 后续接入 plan/订阅时，订阅是挂在 workspace 而不是 user

为什么不直接用 workspace.id：
- 老 user 还没建 workspace；avoid 强制迁移
- 命名空间前缀让两类 id 在同一张表里互斥共存
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


# 单进程缓存：避免每次启动 pipeline 都查 workspaces 表
# key=user_id, value=(tenant_id, expires_at)
_TENANT_CACHE_TTL_SEC = 60.0
_tenant_cache: dict[str, tuple[str, float]] = {}


def _engine():
    return create_engine(get_settings().database_url_sync)


# ── plan → 默认配额映射 ────────────────────────────────────────────────────
# 这里只描述「新 tenant 第一次落库时的默认值」。已落库的 row 用户/管理员可手动改写
# `monthly_limit_usd` / `concurrent_max`，本模块不会覆盖。
PLAN_DEFAULTS: dict[str, dict[str, float]] = {
    "free":     {"monthly_limit_usd": 10.0,   "concurrent_max": 2},
    "standard": {"monthly_limit_usd": 100.0,  "concurrent_max": 5},
    "premium":  {"monthly_limit_usd": 500.0,  "concurrent_max": 10},
    "enterprise": {"monthly_limit_usd": 5000.0, "concurrent_max": 30},
}


@dataclass
class TenantContext:
    tenant_id: str
    user_id: str
    plan: str
    display_name: Optional[str] = None
    workspace_id: Optional[str] = None  # 若解析自 workspace 则非空


def resolve_tenant_id(user_id: Optional[str], file_id: Optional[str] = None) -> str:
    """返回 tenant_id（带命名空间前缀）。

    匿名（user_id 为空）→ 固定 `anon:default`，所有匿名 run 共享一桶（v1 行为兼容）。
    """
    if not user_id:
        return "anon:default"

    cached = _tenant_cache.get(user_id)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]

    tenant_id = f"u:{user_id}"  # 兜底
    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id FROM workspaces
                     WHERE owner_id = :uid
                     ORDER BY created_at ASC
                     LIMIT 1
                    """
                ),
                {"uid": user_id},
            ).fetchone()
            if row and row[0]:
                tenant_id = f"ws:{row[0]}"
    except Exception:  # pragma: no cover - workspace 表缺失也不阻断
        logger.exception("resolve_tenant_id workspace lookup failed user=%s", user_id)

    _tenant_cache[user_id] = (tenant_id, now + _TENANT_CACHE_TTL_SEC)
    return tenant_id


def resolve_tenant_context(
    user_id: Optional[str],
    *,
    file_id: Optional[str] = None,
    user_plan: Optional[str] = None,
) -> TenantContext:
    """返回完整 tenant 上下文，包含 plan / display_name / workspace_id。"""
    if not user_id:
        return TenantContext(
            tenant_id="anon:default",
            user_id="",
            plan="free",
            display_name="(anonymous)",
        )

    plan = user_plan or "free"
    tid = resolve_tenant_id(user_id)
    workspace_id: Optional[str] = None
    display_name: Optional[str] = None

    if tid.startswith("ws:"):
        workspace_id = tid[3:]
        try:
            with _engine().connect() as conn:
                row = conn.execute(
                    text("SELECT name FROM workspaces WHERE id = :wid"),
                    {"wid": workspace_id},
                ).fetchone()
                if row:
                    display_name = row[0]
        except Exception:  # pragma: no cover
            logger.exception("workspace name lookup failed wid=%s", workspace_id)
    else:
        # u:{user_id} → 用 user.email 当 display
        try:
            with _engine().connect() as conn:
                row = conn.execute(
                    text("SELECT email, plan FROM users WHERE id = :uid"),
                    {"uid": user_id},
                ).fetchone()
                if row:
                    display_name = row[0]
                    if not user_plan:
                        plan = row[1] or "free"
        except Exception:  # pragma: no cover
            logger.exception("user lookup failed uid=%s", user_id)

    return TenantContext(
        tenant_id=tid,
        user_id=user_id,
        plan=plan,
        display_name=display_name,
        workspace_id=workspace_id,
    )


def plan_defaults(plan: str) -> dict[str, float]:
    """按 plan 取默认 monthly_limit_usd / concurrent_max；未知 plan 兜底 free。"""
    return PLAN_DEFAULTS.get(plan, PLAN_DEFAULTS["free"])


def clear_cache() -> None:
    """单元测试用 —— 强制下次 resolve 重新读 DB。"""
    _tenant_cache.clear()


__all__ = [
    "PLAN_DEFAULTS",
    "TenantContext",
    "resolve_tenant_id",
    "resolve_tenant_context",
    "plan_defaults",
    "clear_cache",
]
