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


# ────────────────────────────────────────────────────────────────────────────
# Track-27 · editor / viewer 写权限分级
# ────────────────────────────────────────────────────────────────────────────
#
# 在 Track-24 ``is_admin`` 的二元判定之上扩展真 RBAC：
#
#   admin   ─ 可以做计费 / 全平台管理（含原 admin 邮箱白名单 fallback）
#   editor  ─ 可以创建 / 修改 / 删除内容（versions / publish_plans / pipeline 启停）
#   viewer  ─ 仅读
#
# 关键差异（与 ``is_admin`` 对比）
# ------------------------------
# 1. ``is_editor`` / ``is_viewer`` **不**走邮箱白名单 fallback：editor / viewer
#    必须真在 ``team_members`` 表里有行；让运营 / dev 误把 admin 邮箱当 editor
#    用的口子永久封死。``ADMIN_EMAILS`` 仅对 admin 这一档生效。
# 2. 命中规则同 ``is_admin`` 的 path-1 / path-2：显式 ``workspace_id`` →
#    单 workspace 命中；缺省 → 遍历用户所有 ``team_members``。
# 3. ``require_role(allowed)`` 是 FastAPI ``Depends`` factory，挂在路由
#    decorator 的 ``dependencies=[...]``，不入侵函数签名（与既有
#    ``_require_admin`` 的「函数体内部调用」语义并存而不冲突）。
#
# 不缓存新 helper 的原因
# --------------------
# - ``get_user_role`` 已经缓存 60s，editor/viewer 判定主路径都借用它
# - 「遍历所有 workspace」路径只在 workspace_id 缺省时走，不是热点；
#   多缓存一层会把 cache key 维度炸开（admin/editor/viewer × user × ws），
#   测试里 ``clear_cache`` 也得分别清，得不偿失
from fastapi import Depends, HTTPException

from app.deps import get_current_user


def _user_has_role_in(user_id: str, allowed_roles: set[str]) -> bool:
    """workspace_id 缺省时遍历用户所有 ``team_members``；命中任一 allowed role 即 True。

    与 ``_user_has_admin_membership`` 区别：后者只查 admin 一档（带缓存）；
    本函数支持任意 role 集合（不缓存，调用方自己判断热度）。
    """
    if not user_id or not allowed_roles:
        return False
    try:
        with _engine().connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT role FROM team_members
                     WHERE user_id = :uid
                    """
                ),
                {"uid": user_id},
            ).fetchall()
            user_roles = {str(r[0]).lower() for r in rows if r[0]}
            return bool(user_roles & {r.lower() for r in allowed_roles})
    except Exception:  # pragma: no cover - DB 故障兜底
        logger.exception("_user_has_role_in failed user=%s", user_id)
        return False


def is_editor(user_id: Optional[str], *, workspace_id: Optional[str] = None) -> bool:
    """admin / editor 命中即 True；**不**走邮箱白名单 fallback。

    1. 显式 ``workspace_id`` → 该 workspace 内 role in (admin, editor)
    2. ``workspace_id`` 缺省 → 遍历用户所有 ``team_members``，命中任一 admin/editor

    注意：editor 必须真在 ``team_members`` 表里；``Settings.admin_emails`` 邮箱
    白名单**只对 admin 生效**（保留 demo@example.com 等 dev fallback），不对
    editor / viewer 兜底，避免运营场景误把 admin 邮箱当写权限来用。
    """
    if not user_id:
        return False
    if workspace_id:
        return get_user_role(user_id, workspace_id) in ("admin", "editor")
    return _user_has_role_in(user_id, {"admin", "editor"})


def is_viewer(user_id: Optional[str], *, workspace_id: Optional[str] = None) -> bool:
    """role 非空即 True（admin / editor / viewer 都可读）；不走邮箱 fallback。

    1. 显式 ``workspace_id`` → 该 workspace 内 role 非空
    2. ``workspace_id`` 缺省 → 遍历用户所有 ``team_members``，存在任一行即 True

    用于「最低读权限」鉴权（理论上 v1 没有公开列表端点会调到，留给后续）。
    """
    if not user_id:
        return False
    if workspace_id:
        return get_user_role(user_id, workspace_id) is not None
    return _user_has_role_in(user_id, {"admin", "editor", "viewer"})


def _role_label_zh(allowed: list[str]) -> str:
    """403 detail 用的中文 role 提示（保留英文 role 名 + 中文短语）。"""
    return "/".join(allowed)


def require_role(allowed: list[str]):
    """FastAPI ``Depends`` factory：返回一个可被 ``Depends(...)`` 包裹的 callable。

    用法（不改函数签名，挂在 router decorator 的 dependencies 上）：

        @router.post(
            "/publish-plans",
            dependencies=[Depends(require_role(["admin", "editor"]))],
        )
        async def create_publish_plan(...): ...

    判定顺序
    --------
    1. 若 ``"admin" in allowed``：走 ``is_admin``（含邮箱白名单 fallback，保持
       与 ``_require_admin`` / Track-24 一致），命中即放行
    2. 若 ``"editor" in allowed``：走 ``is_editor``（**不**走邮箱 fallback）
    3. 若 ``"viewer" in allowed``：走 ``is_viewer``（**不**走邮箱 fallback）
    4. 都不命中 → 403，detail 含 ``"需要 X 权限"`` 中文提示

    为什么按这个顺序
    --------------
    - admin 是最高权限，先放行避免 editor 路径误拒（editor 路径不走 email
      fallback，admin 邮箱白名单的 dev 也走不进 team_members）
    - 列入 ``allowed`` 才检查对应 helper：避免「require_role(['editor'])」
      被某个误打的 admin 邮箱 fallback 通过（spec 要求 admin 白名单仅对
      ``"admin" in allowed`` 时生效）
    """

    allowed_set = {r.lower() for r in allowed}

    def _check(current_user=Depends(get_current_user)) -> None:
        uid = getattr(current_user, "id", None)
        email = getattr(current_user, "email", None)

        if "admin" in allowed_set and is_admin(uid, email=email):
            return
        if "editor" in allowed_set and is_editor(uid):
            return
        if "viewer" in allowed_set and is_viewer(uid):
            return

        raise HTTPException(
            status_code=403,
            detail=f"需要 {_role_label_zh(allowed)} 权限",
        )

    return _check


__all__ = [
    "get_user_role",
    "is_admin",
    "is_editor",
    "is_viewer",
    "require_role",
    "clear_cache",
]
