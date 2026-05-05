"""Track-24 · RBAC v1（workspace member role）。

把 Track-10/14/18/23 一直沿用的「邮箱白名单 admin」升级为：

1. **优先**：``team_members.role == 'admin'``（workspace 级）
2. **兜底**：``Settings.admin_emails`` 邮箱白名单（保留 demo@example.com 兼容）

为什么保留邮箱白名单 fallback
----------------------------
- ``demo@example.com`` 是 fixtures / 烟测 / dev seed 一直依赖的 admin 入口；
  本 Track 已经做的 backfill 只把 workspace owner 自动 admin，但开发机没建过
  workspace 的老 user / 新拉的 dev 仍要走邮箱白名单
- 生产灾备：``team_members`` 表如果某次迁移 / 误删全没了，admin 邮箱仍能登录
  feature flags 后台手动恢复
- Settings.admin_emails 已是 Track-23 落库的字段，零代码改动；本模块只做调用

接口
----
``get_user_role(user_id, workspace_id)``：返某 workspace 内某 user 的 role
（``admin`` / ``editor`` / ``viewer`` / None）；user 不在该 workspace 时 None

``is_admin(user_id, *, workspace_id=None, email=None)``：admin 综合判定

   - 显式 ``workspace_id`` → 仅当该 workspace 内 role==admin 命中
   - workspace_id 缺 → 遍历 user 所有 team_members，命中任意 admin 即 True
   - 都没命中 → fallback 邮箱白名单（``_is_admin_email``）

设计取舍
--------
- **60s 内存缓存**：与 ``services/pipeline/tenant.py`` 同 pattern；
  pipeline 启动 / admin UI 刷新都不会高频，缓存只为避免 N+1（一个 run 内
  多个 step 都问同一句"你是 admin 吗"）
- **缓存 key 区分维度**：``(user_id, workspace_id_or_None)`` 互不污染；
  email fallback 不缓存（``_is_admin_email`` 本身已是 set 内查，O(1)）
- **fail-open vs fail-closed**：DB 读失败时返 None / False，并落 log；不抛
  HTTPException（避免管道侧调用方需要 try/except）。鉴权层会自然走 403 路径
- **不依赖 ORM**：直接用 ``create_engine + text``，与 admin_flags / cost 同款，
  避免引入 AsyncSession 让单元测变难（参考 conftest 里 _run+SimpleNamespace pattern）
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── 内存缓存 ────────────────────────────────────────────────────────────────
# key = (user_id, workspace_id_or_None) → value = (role_or_None, expires_at)
# workspace_id=None 的项缓存"用户在任意 workspace 的最高 role"（实质是 'admin' / 'member' / None）
_ROLE_CACHE_TTL_SEC = 60.0
_role_cache: dict[tuple[str, Optional[str]], tuple[Optional[str], float]] = {}


def _engine():
    return create_engine(get_settings().database_url_sync)


# ── 邮箱白名单 fallback ─────────────────────────────────────────────────────
# 不直接 import ``app.routers.admin_flags`` 避免循环：admin_flags 反过来
# import 本模块。把 ``_is_admin_email`` 的逻辑在这里复述一遍（同样从
# ``Settings.admin_emails`` 读 + demo fallback），让两边互为冗余的兜底。
_FALLBACK_ADMIN_EMAIL = "demo@example.com"


def _allowed_admin_emails() -> set[str]:
    raw = get_settings().admin_emails or ""
    items = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if items:
        return items
    return {_FALLBACK_ADMIN_EMAIL}


def _is_admin_email(email: Optional[str]) -> bool:
    return bool(email) and email.lower() in _allowed_admin_emails()


# ── 核心查询 ────────────────────────────────────────────────────────────────


def get_user_role(user_id: Optional[str], workspace_id: str) -> Optional[str]:
    """返 user 在 workspace 内的 role；不在该 workspace 时返 None。

    返回值是 ``team_members.role`` 列上的原值（``admin`` / ``editor`` /
    ``viewer``），caller 自己语义化判断；本函数不抛异常 / 不回退到邮箱白名单。
    """
    if not user_id or not workspace_id:
        return None

    cache_key = (user_id, workspace_id)
    cached = _role_cache.get(cache_key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]

    role: Optional[str] = None
    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT role FROM team_members
                     WHERE user_id = :uid AND workspace_id = :wid
                     LIMIT 1
                    """
                ),
                {"uid": user_id, "wid": workspace_id},
            ).fetchone()
            if row and row[0]:
                role = str(row[0]).lower()
    except Exception:  # pragma: no cover - DB 故障兜底
        logger.exception(
            "get_user_role failed user=%s workspace=%s", user_id, workspace_id
        )
        return None

    _role_cache[cache_key] = (role, now + _ROLE_CACHE_TTL_SEC)
    return role


def _user_has_admin_membership(user_id: str) -> bool:
    """workspace_id 缺省时遍历用户所有 team_members；命中任意 admin 即 True。"""
    cache_key = (user_id, None)
    cached = _role_cache.get(cache_key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0] == "admin"

    role: Optional[str] = None
    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT role FROM team_members
                     WHERE user_id = :uid AND role = 'admin'
                     LIMIT 1
                    """
                ),
                {"uid": user_id},
            ).fetchone()
            if row:
                role = "admin"
    except Exception:  # pragma: no cover - DB 故障兜底
        logger.exception("_user_has_admin_membership failed user=%s", user_id)
        return False

    _role_cache[cache_key] = (role, now + _ROLE_CACHE_TTL_SEC)
    return role == "admin"


def is_admin(
    user_id: Optional[str],
    *,
    workspace_id: Optional[str] = None,
    email: Optional[str] = None,
) -> bool:
    """admin 综合判定（三路径）。

    1. 显式 ``workspace_id`` → ``team_members`` 行内 role=='admin'
    2. ``workspace_id`` 缺 → 遍历用户所有 workspace，任意 admin 即命中
    3. 都不命中 → fallback ``_is_admin_email(email)``（保留 demo@example.com 兼容）

    user_id 缺也允许（匿名 / 探测）：直接进 fallback；
    fallback 也不命中 → False。
    """
    # 路径 1：显式 workspace
    if user_id and workspace_id:
        if get_user_role(user_id, workspace_id) == "admin":
            return True
        # 显式 workspace 不命中也允许 fallback；是 backlog 卡片的「邮箱白名单兜底」语义
        return _is_admin_email(email)

    # 路径 2：遍历用户所有 workspace
    if user_id:
        if _user_has_admin_membership(user_id):
            return True

    # 路径 3：邮箱白名单 fallback
    return _is_admin_email(email)


# ── 测试 / dev 工具 ──────────────────────────────────────────────────────────


def clear_cache() -> None:
    """单元测试用 —— 强制下次 is_admin / get_user_role 重新读 DB。"""
    _role_cache.clear()


__all__ = [
    "get_user_role",
    "is_admin",
    "clear_cache",
]
