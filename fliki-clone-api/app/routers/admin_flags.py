"""Admin feature flag 路由（Track-10 灰度发布 / canary）。

提供 admin 维度的 GET / PUT / DELETE：
- `GET    /admin/feature-flags?tenant_id=...`           列某 tenant 全部 flag
- `GET    /admin/feature-flags/{tenant_id}/{flag_name}` 读单个 flag value
- `PUT    /admin/feature-flags/{tenant_id}/{flag_name}` upsert flag value
- `DELETE /admin/feature-flags/{tenant_id}/{flag_name}` 删除 flag

权限简化（v1）
--------------
按 backlog 卡片要求：`user.email in ALLOWED_ADMINS`。
ALLOWED_ADMINS 来源（按优先级）：
1. 环境变量 `ADMIN_EMAILS=foo@bar.com,baz@qux.com`（逗号分隔）
2. fallback 内置默认（`demo@example.com` —— 与 fixtures 里的 demo user 一致，
   方便本地直接测试；生产 env 必须显式覆盖）

为什么不放 settings：Track-01 互斥锁占了 `app/config.py`；
读 env 直读即可，避免越界改 config。后续可由协调者把它迁到 settings。

为什么不引入完整 RBAC：
- v1 只需要"关掉灰度按钮的 self-serve 入口"
- 完整 RBAC 是 L-05 长尾任务（workspace member editor/viewer）

为什么 tenant_id 是路径参数：
- admin 操作的对象本来就是「某 tenant 的某 flag」，URL 自描述
- 与配额 v2 的 tenant 命名空间一致：`ws:{wid}` / `u:{uid}` / `anon:default`
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.deps import CurrentUser
from app.services.pipeline import feature_flags as flag_service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/admin/feature-flags", tags=["Admin / Feature Flags"])


# ── admin 鉴权（简化版）─────────────────────────────────────────────────────


def _allowed_admins() -> set[str]:
    """读 env `ADMIN_EMAILS`（逗号分隔）；无则 fallback 到 demo@example.com。

    注意保留 dev fallback：fixtures / 烟测里 demo user 的邮箱就是这个。
    """
    raw = os.environ.get("ADMIN_EMAILS", "")
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if items:
        return set(items)
    return {"demo@example.com"}


def _require_admin(current_user: CurrentUser) -> None:
    """简化版 admin gate：user.email 必须命中白名单。"""
    email = (current_user.email or "").lower()
    if email not in _allowed_admins():
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


# ── 路由 ─────────────────────────────────────────────────────────────────────


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
