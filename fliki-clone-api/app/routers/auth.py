import secrets
from datetime import timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DB, CurrentUser
from app.models.user import User
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UpdateMeRequest,
    UpdateNotificationsRequest,
    UpdatePasswordRequest,
    UserOut,
    CreditsInfo,
    MessageResponse,
)
from app.utils.auth import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])
me_router = APIRouter(tags=["Me"])
settings = get_settings()

COOKIE_MAX_AGE = settings.jwt_expires_days * 86400


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


def _user_to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        plan=user.plan,
        credits=CreditsInfo(used=user.credits_used, total=user.credits_total),
        youtube_channel_ids=user.youtube_channel_ids or [],
    )


# ── Register ──────────────────────────────────────────────────────────────────
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, response: Response, db: DB):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name or body.email.split("@")[0],
        hashed_password=hash_password(body.password),
        referral_code=secrets.token_urlsafe(8),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return _user_to_out(user)


# ── Login ─────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=UserOut)
async def login(body: LoginRequest, response: Response, db: DB):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    return _user_to_out(user)


# ── Logout ────────────────────────────────────────────────────────────────────
@router.post("/logout", response_model=MessageResponse)
async def logout(response: Response):
    response.delete_cookie("token", path="/")
    return MessageResponse(message="Logged out")


# ── OAuth: Google ─────────────────────────────────────────────────────────────
@router.get("/oauth/google")
async def oauth_google_redirect():
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": f"{settings.frontend_url}/api/auth/oauth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)


@router.get("/oauth/google/callback")
async def oauth_google_callback(code: str, response: Response, db: DB):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": f"{settings.frontend_url}/api/auth/oauth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        token_data = token_res.json()
        user_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
        )
        info = user_res.json()

    result = await db.execute(select(User).where(User.google_id == info["id"]))
    user = result.scalar_one_or_none()

    if not user:
        # Try by email
        result = await db.execute(select(User).where(User.email == info["email"]))
        user = result.scalar_one_or_none()
        if user:
            user.google_id = info["id"]
        else:
            user = User(
                email=info["email"],
                name=info.get("name", info["email"].split("@")[0]),
                google_id=info["id"],
                referral_code=secrets.token_urlsafe(8),
            )
            db.add(user)

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{settings.frontend_url}/app")


# ── OAuth: GitHub ─────────────────────────────────────────────────────────────
@router.get("/oauth/github")
async def oauth_github_redirect():
    from urllib.parse import urlencode
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": f"{settings.frontend_url}/api/auth/oauth/github/callback",
        "scope": "user:email",
    }
    url = "https://github.com/login/oauth/authorize?" + urlencode(params)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)


@router.get("/oauth/github/callback")
async def oauth_github_callback(code: str, response: Response, db: DB):
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        access_token = token_res.json().get("access_token")

        user_res = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        gh_user = user_res.json()

        email_res = await client.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails = email_res.json()
        primary_email = next((e["email"] for e in emails if e.get("primary")), None)

    result = await db.execute(select(User).where(User.github_id == str(gh_user["id"])))
    user = result.scalar_one_or_none()

    if not user and primary_email:
        result = await db.execute(select(User).where(User.email == primary_email))
        user = result.scalar_one_or_none()
        if user:
            user.github_id = str(gh_user["id"])
        else:
            user = User(
                email=primary_email or f"gh_{gh_user['id']}@github.local",
                name=gh_user.get("name") or gh_user.get("login", ""),
                github_id=str(gh_user["id"]),
                referral_code=secrets.token_urlsafe(8),
            )
            db.add(user)

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    _set_auth_cookie(response, token)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"{settings.frontend_url}/app")


# ── Me ────────────────────────────────────────────────────────────────────────
@me_router.get("/me", response_model=UserOut)
async def get_me(current_user: CurrentUser):
    return _user_to_out(current_user)


@me_router.patch("/me", response_model=UserOut)
async def update_me(body: UpdateMeRequest, current_user: CurrentUser, db: DB):
    if body.name is not None:
        current_user.name = body.name
    if body.youtube_channel_ids is not None:
        current_user.youtube_channel_ids = body.youtube_channel_ids
    await db.commit()
    await db.refresh(current_user)
    return _user_to_out(current_user)


@me_router.patch("/me/password", response_model=MessageResponse)
async def update_password(body: UpdatePasswordRequest, current_user: CurrentUser, db: DB):
    if not current_user.hashed_password or not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    await db.commit()
    return MessageResponse(message="Password updated")


@me_router.patch("/me/notifications", response_model=MessageResponse)
async def update_notifications(body: UpdateNotificationsRequest, current_user: CurrentUser, db: DB):
    current_user.email_notifications = body.email_notifications
    await db.commit()
    return MessageResponse(message="Notification preferences updated")
