"""Admin feature flag 路由（Track-10 灰度发布 / canary）。

提供 admin 维度的 GET / PUT / DELETE：
- `GET    /admin/feature-flags?tenant_id=...`           列某 tenant 全部 flag
- `GET    /admin/feature-flags/{tenant_id}/{flag_name}` 读单个 flag value
- `PUT    /admin/feature-flags/{tenant_id}/{flag_name}` upsert flag value
- `DELETE /admin/feature-flags/{tenant_id}/{flag_name}` 删除 flag

权限（Track-24 RBAC v1）
------------------------
admin 判定流程（``rbac.is_admin`` 内部三路径）：
1. ``team_members.role == 'admin'``（workspace 级；优先）
2. workspace 缺省 → 遍历用户所有 workspace 命中任一 admin 即可
3. 都没命中 → fallback ``Settings.admin_emails`` 邮箱白名单
   （保留 ``demo@example.com`` 兼容 fixtures / dev seed）

为什么仍保留 ``_is_admin_email`` 这个本地函数（不删）
---------------------------------------------------
- ``/me`` 探测端点、``_require_admin`` 都从 ``rbac.is_admin`` 走，统一入口
- ``_is_admin_email`` 仍作为「纯邮箱白名单」工具保留，给已有测试 + 兜底场景使用
  （rbac 模块也内部复述了同样的逻辑，互为冗余的 fallback）
- Track-23 已把 ``Settings.admin_emails`` 落库；本 Track 在其上加 RBAC 主路径

迁移说明（Track-23 → Track-24）
-------------------------------
- Track-23 把 ``ADMIN_EMAILS`` 从 env 直读迁回 ``Settings.admin_emails``
- Track-24 把 admin 判定主路径从「邮箱白名单」升级为「team_members.role」
  邮箱白名单作为 fallback 兜底（不删 ``_is_admin_email``）

为什么 tenant_id 是路径参数：
- admin 操作的对象本来就是「某 tenant 的某 flag」，URL 自描述
- 与配额 v2 的 tenant 命名空间一致：`ws:{wid}` / `u:{uid}` / `anon:default`
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.deps import CurrentUser
from app.services.auth import rbac
from app.services.pipeline import feature_flags as flag_service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin/feature-flags", tags=["Admin / Feature Flags"])


# ── admin 鉴权（简化版）─────────────────────────────────────────────────────


_FALLBACK_ADMIN_EMAIL = "demo@example.com"


def _allowed_admins() -> set[str]:
    """读 `Settings.admin_emails`，按逗号 split + strip + lower + 去空 + set 化。

    解析后为空（env 显式设为 ""）→ fallback {"demo@example.com"} 保留 dev
    可用性：fixtures / 烟测里 demo user 的邮箱就是这个。
    """
    raw = get_settings().admin_emails or ""
    items = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if items:
        return items
    return {_FALLBACK_ADMIN_EMAIL}


def _is_admin_email(email: Optional[str]) -> bool:
    """纯邮箱白名单判定（保留作为 ``rbac.is_admin`` 的 fallback 工具）。

    Track-24 起，admin 主入口走 ``rbac.is_admin``（先查 team_members.role，
    再 fallback 邮箱白名单）；本函数仍被 ``rbac`` 模块内部复述 + 测试直接调
    用，作为兜底兼容保留（不删除）。
    """
    return bool(email) and email.lower() in _allowed_admins()


def _is_admin_user(current_user: CurrentUser) -> bool:
    """统一的 admin 判定入口；从 ``current_user`` 抽 id + email 喂给 rbac。

    单独抽 helper 是为了让 `_require_admin` / `/me` 端点共享同一份判定逻辑，
    避免两处 if 分支漂移。
    """
    return rbac.is_admin(
        current_user.id,
        email=current_user.email,
    )


def _require_admin(current_user: CurrentUser) -> None:
    """admin gate（Track-24 RBAC v1）。

    判定主路径：``team_members.role == 'admin'``；
    邮箱白名单作为 fallback 兜底（保留 demo@example.com 兼容）。
    """
    if not _is_admin_user(current_user):
        raise HTTPException(
            status_code=403,
            detail=(
                "admin only; ask coordinator to add you as workspace admin "
                "or to ADMIN_EMAILS"
            ),
        )


# ── Schema ──────────────────────────────────────────────────────────────────


class FeatureFlagOut(BaseModel):
    tenant_id: str
    flag_name: str
    value_json: dict[str, Any]


class SetFlagBody(BaseModel):
    """upsert 请求体；`value` 必须是 JSON object（dict）。"""

    value: dict[str, Any] = Field(
        ...,
        description=(
            "JSON object 形态。典型："
            ' {"pct": 50} / {"enabled": true} / {"variant": "v4"}'
        ),
    )


class FlagListOut(BaseModel):
    tenant_id: str
    flags: dict[str, dict[str, Any]]
    known_flags: dict[str, str]


class DeleteResult(BaseModel):
    tenant_id: str
    flag_name: str
    deleted: bool


class TenantSummary(BaseModel):
    """`/tenants` 列表项；admin UI 顶部 tenant 选择器用。"""

    tenant_id: str
    flag_count: int


class TenantsListOut(BaseModel):
    tenants: list[TenantSummary]
    known_flags: dict[str, str]


class AdminMeOut(BaseModel):
    """前端 `Sidebar` 探测端点；非 admin 也能调，不抛 403，避免污染开发台。

    Track-27 起新加 `role` / `is_editor` / `is_viewer` 三字段，让前端按钮按
    role 灰化（viewer 不能点 / editor 不能点 admin-only 计费）。
    `is_admin` 字段保留（与 Track-14/24 既有 7 case 兼容；前端 sidebar 仍只看 is_admin）。

    role 字段语义
    -------------
    - `"admin"` / `"editor"` / `"viewer"`：在某 workspace 真有 team_members 行；
      没显式 `workspace_id` 时，返「用户最高的那一档」（admin > editor > viewer）
    - `null`：用户没在任何 workspace 登记 team_members（dev / 邮箱 fallback admin）
      但 `is_admin` 仍可能是 True（走邮箱白名单 fallback）
    """

    is_admin: bool
    is_editor: bool = False
    is_viewer: bool = False
    role: Optional[str] = None
    email: Optional[str] = None


# ── 路由 ─────────────────────────────────────────────────────────────────────


def _resolve_user_top_role(current_user: CurrentUser) -> Optional[str]:
    """返用户在「任意 workspace」中的最高 role（admin > editor > viewer）。

    Track-27 新加：让前端 `useCurrentRole` 一次拿到 role 就能决定按钮启用
    / 灰化，不必再二次探测。

    注意：本函数读 `team_members` 一次（无缓存；rbac 模块自己有 60s cache
    覆盖 `get_user_role`，但本聚合函数走的是单独 SQL，频率极低不缓存）。
    """
    uid = getattr(current_user, "id", None)
    if not uid:
        return None
    try:
        engine = create_engine(get_settings().database_url_sync)
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT DISTINCT role FROM team_members WHERE user_id = :uid"),
                {"uid": uid},
            ).fetchall()
            roles = {str(r[0]).lower() for r in rows if r[0]}
    except Exception:  # pragma: no cover
        logger.exception("_resolve_user_top_role failed user=%s", uid)
        return None
    if "admin" in roles:
        return "admin"
    if "editor" in roles:
        return "editor"
    if "viewer" in roles:
        return "viewer"
    return None


@router.get("/me", response_model=AdminMeOut)
async def admin_self_check(current_user: CurrentUser) -> AdminMeOut:
    """登录用户探测自己是否 admin / editor / viewer。

    单独留 endpoint 而不复用 `/me` 是为了：
    1. 不越界改 `app/routers/auth.py` 的 UserOut（互斥锁规则 1.4 / 1.5 之外，
       schemas 改动也有跨 Track 影响半径）
    2. 让前端 `Sidebar` 单次轻量探测就能决定是否渲染 admin 入口
       （非 admin 不会拉 `/tenants` 列表，避免一进 app 就触发 403 噪音）

    Track-27 起新加 `role` / `is_editor` / `is_viewer` 字段：
    - `is_admin`：保留 Track-14 既有语义（含邮箱白名单 fallback）
    - `is_editor`：仅 team_members.role in (admin, editor) 命中（**不**走邮箱兜底）
    - `is_viewer`：team_members 任意行命中（**不**走邮箱兜底）
    - `role`：用户最高 role（admin > editor > viewer），用于 tooltip 文案
    """
    return AdminMeOut(
        is_admin=_is_admin_user(current_user),
        is_editor=rbac.is_editor(current_user.id),
        is_viewer=rbac.is_viewer(current_user.id),
        role=_resolve_user_top_role(current_user),
        email=current_user.email,
    )


@router.get("/tenants", response_model=TenantsListOut)
async def list_tenants(current_user: CurrentUser) -> TenantsListOut:
    """列出有 flag 落库的 tenant + 每个 tenant 的 flag 数量。

    只读 `feature_flags` 一张表；不去碰 `tenant_quotas`（v2 配额表里 tenant 多得多，
    跟 admin UI 关心的「真的设过 flag」不是一回事；admin 可以从 quota 列表手填一个
    新 tenant 然后调 PUT 落第一条 flag）。
    """
    _require_admin(current_user)
    try:
        engine = create_engine(get_settings().database_url_sync)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT tenant_id, COUNT(*) AS flag_count
                      FROM feature_flags
                     GROUP BY tenant_id
                     ORDER BY tenant_id ASC
                    """
                )
            ).fetchall()
    except Exception as exc:  # pragma: no cover - 表缺失等 dev 环境兜底
        logger.exception("list_tenants failed")
        raise HTTPException(
            status_code=503,
            detail=f"feature_flags read failed: {type(exc).__name__}",
        ) from exc

    tenants = [
        TenantSummary(tenant_id=str(r[0]), flag_count=int(r[1] or 0)) for r in rows
    ]
    return TenantsListOut(tenants=tenants, known_flags=flag_service.KNOWN_FLAGS)


@router.get("", response_model=FlagListOut)
async def list_flags(
    current_user: CurrentUser,
    tenant_id: str = Query(..., description="目标 tenant_id（ws:{wid} / u:{uid}）"),
) -> FlagListOut:
    """列某 tenant 全部 flag；附 `known_flags` 文档便于前端 hint。"""
    _require_admin(current_user)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    flags_map = flag_service.load_for_tenant(tenant_id)
    return FlagListOut(
        tenant_id=tenant_id,
        flags=flags_map,
        known_flags=flag_service.KNOWN_FLAGS,
    )


@router.get("/{tenant_id}/{flag_name}", response_model=FeatureFlagOut)
async def get_flag(
    tenant_id: str,
    flag_name: str,
    current_user: CurrentUser,
) -> FeatureFlagOut:
    _require_admin(current_user)
    val: Optional[dict[str, Any]] = flag_service.get_flag(tenant_id, flag_name)
    if val is None:
        raise HTTPException(status_code=404, detail="flag not set for this tenant")
    return FeatureFlagOut(
        tenant_id=tenant_id, flag_name=flag_name, value_json=val
    )


@router.put("/{tenant_id}/{flag_name}", response_model=FeatureFlagOut)
async def put_flag(
    tenant_id: str,
    flag_name: str,
    body: SetFlagBody,
    current_user: CurrentUser,
) -> FeatureFlagOut:
    """upsert flag value；存在覆盖、不存在 INSERT。"""
    _require_admin(current_user)
    try:
        written = flag_service.set_flag(tenant_id, flag_name, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FeatureFlagOut(
        tenant_id=tenant_id, flag_name=flag_name, value_json=written
    )


@router.delete("/{tenant_id}/{flag_name}", response_model=DeleteResult)
async def delete_flag(
    tenant_id: str,
    flag_name: str,
    current_user: CurrentUser,
) -> DeleteResult:
    _require_admin(current_user)
    deleted = flag_service.delete_flag(tenant_id, flag_name)
    return DeleteResult(
        tenant_id=tenant_id, flag_name=flag_name, deleted=deleted
    )


__all__ = ["router"]
