import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.team import TeamMember, Workspace
from app.schemas import InviteMemberRequest, MessageResponse, PatchMemberRequest, TeamMemberOut

router = APIRouter(tags=["Team"])
settings = get_settings()


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
