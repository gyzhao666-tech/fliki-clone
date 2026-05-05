from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.referral import Referral, RewardTask
from app.schemas import MessageResponse, ReferralStatsOut, RewardTaskOut, SubmitRewardRequest

router = APIRouter(tags=["Rewards & Referrals"])
settings = get_settings()

REWARD_CREDITS = {
    "share_twitter": 2,
    "share_youtube": 3,
    "share_linkedin": 2,
    "review_g2": 5,
}


@router.get("/rewards", response_model=list[RewardTaskOut])
async def list_rewards(current_user: CurrentUser, db: DB):
    result = await db.execute(
        select(RewardTask).where(RewardTask.user_id == current_user.id)
    )
    return [
        RewardTaskOut(
            id=t.id, task_type=t.task_type, status=t.status,
            credits_awarded=int(t.credits_awarded or 0), submitted_at=t.submitted_at,
        )
        for t in result.scalars().all()
    ]


@router.post("/rewards/submit", response_model=RewardTaskOut)
async def submit_reward(body: SubmitRewardRequest, current_user: CurrentUser, db: DB):
    existing = await db.execute(
        select(RewardTask).where(
            RewardTask.user_id == current_user.id,
            RewardTask.task_type == body.task_type,
            RewardTask.status.in_(["submitted", "approved"]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Task already submitted")

    task = RewardTask(
        user_id=current_user.id,
        task_type=body.task_type,
        status="submitted",
        screenshot_url=body.screenshot_url,
        submitted_at=datetime.now(timezone.utc),
        credits_awarded=0,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return RewardTaskOut(
        id=task.id, task_type=task.task_type, status=task.status,
        credits_awarded=0, submitted_at=task.submitted_at,
    )


@router.get("/referrals", response_model=ReferralStatsOut)
async def get_referral_stats(current_user: CurrentUser, db: DB):
    count_result = await db.execute(
        select(func.count()).where(Referral.referrer_id == current_user.id)
    )
    total = count_result.scalar_one()

    credited_result = await db.execute(
        select(func.count()).where(
            Referral.referrer_id == current_user.id,
            Referral.credited_at.isnot(None),
        )
    )
    credited = credited_result.scalar_one()
    credits_earned = credited * 5  # 5 credits per successful referral

    referral_link = f"{settings.frontend_url}/signup?ref={current_user.referral_code or ''}"
    return ReferralStatsOut(
        total_referred=total,
        credits_earned=credits_earned,
        referral_link=referral_link,
    )


@router.get("/referrals/link")
async def get_referral_link(current_user: CurrentUser):
    if not current_user.referral_code:
        import secrets
        current_user.referral_code = secrets.token_urlsafe(8)

    return {
        "link": f"{settings.frontend_url}/signup?ref={current_user.referral_code}",
        "code": current_user.referral_code,
    }
