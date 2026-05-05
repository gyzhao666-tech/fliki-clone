"""Admin feature flag 路由（Track-10 灰度发布 / canary）。

提供 admin 维度的 GET / PUT / DELETE：
- `GET    /admin/feature-flags?tenant_id=...`           列某 tenant 全部 flag
- `GET    /admin/feature-flags/{tenant_id}/{flag_name}` 读单个 flag value
- `PUT    /admin/feature-flags/{tenant_id}/{flag_name}` upsert flag value
- `DELETE /admin/feature-flags/{tenant_id}/{flag_name}` 删除 flag

权限简化（v1）
--------------
按 backlog 卡片要求：`user.email in ALLOWED_ADMINS`。
ALLOWED_ADMINS 来源（Track-23 起）：
1. `Settings.admin_emails`（pydantic-settings 自动从 env `ADMIN_EMAILS`
   注入，逗号分隔字符串）
2. 解析后为空 → fallback 内置默认 `demo@example.com`（与 fixtures 里的
   demo user 一致，方便本地直接测试；生产 env 必须显式覆盖）

迁移说明（Track-23）
-------------------
原 v1 实现 `os.environ.get("ADMIN_EMAILS", "")` 直读；Track-01 互斥锁解除后
迁回 `app/config.py::Settings.admin_emails`，让 IDE 提示 / 全量 settings
列表里有这一项，避免散落在多个 router 自己读 env。

为什么不引入完整 RBAC：
- v1 只需要"关掉灰度按钮的 self-serve 入口"
- 完整 RBAC 是 L-05 / Track-24 长尾任务（workspace member editor/viewer）

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
    """无副作用的 admin 判定；同时给 `_require_admin` 与 `/me` 探测端点用。"""
    return bool(email) and email.lower() in _allowed_admins()


def _require_admin(current_user: CurrentUser) -> None:
    """简化版 admin gate：user.email 必须命中白名单。"""
    if not _is_admin_email(current_user.email):
        raise HTTPException(
            status_code=403,
            detail="admin only; ask coordinator to add your email to ADMIN_EMAILS",
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
    """前端 `Sidebar` 探测端点；非 admin 也能调，不抛 403，避免污染开发台。"""

    is_admin: bool
    email: Optional[str] = None


# ── 路由 ─────────────────────────────────────────────────────────────────────


@router.get("/me", response_model=AdminMeOut)
async def admin_self_check(current_user: CurrentUser) -> AdminMeOut:
    """登录用户探测自己是否 admin。

    单独留 endpoint 而不复用 `/me` 是为了：
    1. 不越界改 `app/routers/auth.py` 的 UserOut（互斥锁规则 1.4 / 1.5 之外，
       schemas 改动也有跨 Track 影响半径）
    2. 让前端 `Sidebar` 单次轻量探测就能决定是否渲染 admin 入口
       （非 admin 不会拉 `/tenants` 列表，避免一进 app 就触发 403 噪音）
    """
    return AdminMeOut(
        is_admin=_is_admin_email(current_user.email),
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
