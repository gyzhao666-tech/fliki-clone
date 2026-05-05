import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.team import TeamMember, Workspace
from app.schemas import InviteMemberRequest, MessageResponse, PatchMemberRequest, TeamMemberOut

router = APIRouter(tags=["Team"])
settings = get_settings()


# ── Track-30 · workspace 切换（GET /team/workspaces/me） ─────────────────────
# 用户首屏 workspace selector 批量探测当前可见的所有 workspace + 各自 role。
# 返回结构与前端 `lib/workspaces.ts::WorkspaceMembership` 一一对应。


class WorkspaceMembershipOut(BaseModel):
    id: str
    name: str
    role: str  # admin | editor | viewer
    is_owner: bool
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspacesListOut(BaseModel):
    workspaces: list[WorkspaceMembershipOut]


async def _get_or_create_workspace(user_id: str, db: DB) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.owner_id == user_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        workspace = Workspace(owner_id=user_id, name="My Workspace")
        db.add(workspace)
        await db.commit()
        await db.refresh(workspace)
    return workspace


@router.get("/team/members", response_model=list[TeamMemberOut])
async def list_members(current_user: CurrentUser, db: DB):
    workspace = await _get_or_create_workspace(current_user.id, db)
    result = await db.execute(
        select(TeamMember).where(TeamMember.workspace_id == workspace.id)
    )
    return [
        TeamMemberOut(id=m.id, email=m.email, role=m.role, status=m.status, created_at=m.created_at)
        for m in result.scalars().all()
    ]


@router.post("/team/invite", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(body: InviteMemberRequest, current_user: CurrentUser, db: DB):
    workspace = await _get_or_create_workspace(current_user.id, db)
    invite_token = secrets.token_urlsafe(32)
    member = TeamMember(
        workspace_id=workspace.id,
        email=body.email,
        role=body.role,
        status="pending",
        invite_token=invite_token,
    )
    db.add(member)
    await db.commit()

    invite_link = f"{settings.frontend_url}/invite/{invite_token}"
    try:
        from app.utils.email import send_invite_email
        await send_invite_email(body.email, invite_link, current_user.name)
    except Exception:
        pass  # Don't fail if email sending fails

    return MessageResponse(message=f"Invitation sent to {body.email}")


@router.patch("/team/members/{member_id}", response_model=TeamMemberOut)
async def update_member_role(member_id: str, body: PatchMemberRequest, current_user: CurrentUser, db: DB):
    workspace = await _get_or_create_workspace(current_user.id, db)
    result = await db.execute(
        select(TeamMember).where(TeamMember.id == member_id, TeamMember.workspace_id == workspace.id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    member.role = body.role
    await db.commit()
    await db.refresh(member)
    return TeamMemberOut(id=member.id, email=member.email, role=member.role, status=member.status, created_at=member.created_at)


@router.delete("/team/members/{member_id}", response_model=MessageResponse)
async def remove_member(member_id: str, current_user: CurrentUser, db: DB):
    workspace = await _get_or_create_workspace(current_user.id, db)
    result = await db.execute(
        select(TeamMember).where(TeamMember.id == member_id, TeamMember.workspace_id == workspace.id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    await db.delete(member)
    await db.commit()
    return MessageResponse(message="Member removed")


# ── Track-30 · GET /team/workspaces/me ───────────────────────────────────────
@router.get("/team/workspaces/me", response_model=WorkspacesListOut)
async def list_my_workspaces(current_user: CurrentUser, db: DB) -> WorkspacesListOut:
    """列当前 user 所有可见的 workspace + 各自 role。

    数据来源
    --------
    1. ``team_members JOIN workspaces`` 拉所有 ``team_members.user_id == current_user.id``
       的 workspace（user 显式 invite 加入的）；role 取 ``team_members.role``
    2. UNION ``workspaces.owner_id == current_user.id`` 拿 owner 视角；
       owner 已经在 team_members 里时**不**重复计入（取 team_members 的 role —— 与
       Track-24 backfill 语义一致：owner 一定会被一次性 backfill 到
       team_members.role='admin'，但如果之后被 PATCH 降级，UI 也尊重那个降级）
    3. owner-only（没 team_members 行）路径 role 默认 'admin'

    设计取舍
    --------
    - 单 user 通常 ≤ 几十 workspace，两条 SQL 一次查完；不引入 RBAC 缓存（缓存
      用于 hot path 的 is_admin 判定，本端点是首屏批量拉一次）
    - 不抛 404：empty user（没任何 workspace）合法返 ``{"workspaces": []}``
    - 排序：按 ``created_at`` ASC，让前端 selector 默认选最早的（通常是 own）
    """
    user_id = current_user.id

    # 1. team_members JOIN workspaces：user 显式在的所有 workspace
    tm_rows = await db.execute(
        select(Workspace, TeamMember.role)
        .join(TeamMember, TeamMember.workspace_id == Workspace.id)
        .where(TeamMember.user_id == user_id)
    )

    seen: dict[str, WorkspaceMembershipOut] = {}
    for ws, role in tm_rows.all():
        seen[ws.id] = WorkspaceMembershipOut(
            id=ws.id,
            name=ws.name,
            role=(role or "editor").lower(),
            is_owner=(ws.owner_id == user_id),
            created_at=ws.created_at,
        )

    # 2. UNION owner-only workspaces（没在 team_members 里的，role 兜底 admin）
    own_rows = await db.execute(
        select(Workspace).where(Workspace.owner_id == user_id)
    )
    for ws in own_rows.scalars().all():
        if ws.id in seen:
            continue
        seen[ws.id] = WorkspaceMembershipOut(
            id=ws.id,
            name=ws.name,
            role="admin",
            is_owner=True,
            created_at=ws.created_at,
        )

    items = sorted(seen.values(), key=lambda w: (w.created_at, w.id))
    return WorkspacesListOut(workspaces=items)
