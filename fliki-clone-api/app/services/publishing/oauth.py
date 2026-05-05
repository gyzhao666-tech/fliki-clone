"""通用 OAuth 流程帮手（发布执行器 v1）。

只针对「需要 OAuth 拿用户授权才能上传」的平台：v1 只有 YouTube。

流程
----
1. front-end 调 `POST /platforms/{platform}/oauth/start`（带当前 user_id from auth cookie）
   → backend 生成 state（带 user_id + platform + nonce 的 JWT，1h 过期）
   → 拼平台授权 URL `?client_id=...&redirect_uri=...&scope=...&state=...&access_type=offline&prompt=consent`
   → 返 `{authorize_url, state}`，前端 window.location.assign() 过去
2. 用户授权后平台 302 到 `redirect_uri`（即 `/api/production/platforms/{platform}/oauth/callback?code=&state=`）
   → backend 验 state（user_id + platform 匹配）+ POST /token endpoint 换 access/refresh token
   → upsert_credential 落库
   → 302 到 `frontend_url + /app/settings/integrations?platform=...&result=ok`

错误处理
-------
- state 不合法 / 过期 → 400
- 平台返 error → 写到 credential.status='error' + error meta
- network exc → 5xx，让前端重试
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import jwt
import requests

from app.config import get_settings

from . import credentials as creds

logger = logging.getLogger(__name__)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def build_state(user_id: str, platform: str) -> str:
    """signed state 防 CSRF；JWT 1h 过期。"""
    settings = get_settings()
    payload = {
        "uid": user_id,
        "pf": platform,
        "n": secrets.token_urlsafe(8),
        "exp": int(
            (datetime.now(tz=timezone.utc) + timedelta(hours=1)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def parse_state(state: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            state, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise ValueError(f"invalid oauth state: {exc}") from exc
    return payload


def build_redirect_uri(platform: str) -> str:
    """callback URL 必须与平台注册 OAuth 时填的一致。

    用 `api_public_base_url`（默认 http://localhost:8000）；生产环境改 .env 即可。
    """
    base = get_settings().api_public_base_url.rstrip("/")
    return f"{base}/api/production/platforms/{platform}/oauth/callback"


def build_youtube_authorize_url(state: str) -> str:
    settings = get_settings()
    if not settings.google_client_id:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID not configured; cannot start YouTube OAuth"
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": build_redirect_uri("youtube"),
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_youtube_code(code: str) -> dict[str, Any]:
    """code → access_token / refresh_token / expires_in / scope。"""
    settings = get_settings()
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": build_redirect_uri("youtube"),
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"google token exchange http {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def fetch_google_userinfo(access_token: str) -> dict[str, Any]:
    resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"google userinfo http {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()


def complete_youtube_oauth(*, code: str, state: str) -> dict[str, Any]:
    """处理 callback：验 state、换 token、写 credential。返 {user_id, platform, credential}。"""
    parsed = parse_state(state)
    if parsed.get("pf") != "youtube":
        raise ValueError("state platform mismatch")
    user_id = parsed.get("uid")
    if not user_id:
        raise ValueError("state missing user_id")

    token_payload = exchange_youtube_code(code)
    access_token = token_payload["access_token"]
    refresh_token = token_payload.get("refresh_token")
    expires_in = int(token_payload.get("expires_in") or 3600)
    scope_str = str(token_payload.get("scope") or "")
    scopes = [s for s in scope_str.split(" ") if s]
    expires_at = datetime.now(tz=timezone.utc).replace(microsecond=0) + timedelta(
        seconds=expires_in
    )

    # 拿 channel info 当 display_name
    display_name: Optional[str] = None
    external_user_id: Optional[str] = None
    try:
        info = fetch_google_userinfo(access_token)
        display_name = info.get("name") or info.get("email")
        external_user_id = info.get("id")
    except Exception:  # pragma: no cover
        logger.exception("fetch_google_userinfo failed (non-fatal)")

    cred = creds.upsert_credential(
        user_id=user_id,
        platform="youtube",
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
        scope=scopes,
        display_name=display_name,
        external_user_id=external_user_id,
        meta={"granted_at": datetime.now(tz=timezone.utc).isoformat()},
    )
    return {"user_id": user_id, "platform": "youtube", "credential_id": cred.id}


__all__ = [
    "YOUTUBE_SCOPES",
    "build_state",
    "build_youtube_authorize_url",
    "complete_youtube_oauth",
    "parse_state",
]
