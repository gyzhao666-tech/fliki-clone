from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status, Cookie, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.utils.auth import decode_token


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Cookie(default=None, alias="token"),
    authorization: Optional[str] = Header(default=None),
) -> User:
    """
    Resolve the current user from:
    1. HttpOnly cookie `token`
    2. Authorization: Bearer <token> header (for API clients)
    """
    raw_token: Optional[str] = None

    if token:
        raw_token = token
    elif authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = decode_token(raw_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]
