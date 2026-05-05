"""YouTube adapter（真发，依赖用户 OAuth + GOOGLE_CLIENT_ID/SECRET）。

设计取舍
-------
- 真实端点：`POST https://www.googleapis.com/upload/youtube/v3/videos`（resumable upload v2）
- 用户配 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` + 走 OAuth 拿 access/refresh token
  + scope 必须含 `https://www.googleapis.com/auth/youtube.upload`
- 缺凭证 / scope 不足时返 `PublishOutcome(ok=False, error=...)`，不抛异常 → executor 写
  `plan.status='failed' + plan.error=...`，前端显示「YouTube 未授权 / scope 不足」
- 正在跑 v1 时**不真发**，避免误测：把 token 拿到、URL 校验通过即可，但 upload 端点用
  `dry-run` 模式（返 mock external_id）；要真发必须 `plan.confirm_real_publish=true`
  （Track-02 已把这个开关从 `meta_json` 提到独立列；req.confirm_real_publish 由 executor 透传）。
- 真发的 resumable upload 实现细节（chunked PUT / 续传）留给 v2；v1 走简单 `multipart` 一次发。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.config import get_settings

from .base import (
    PlatformAdapter,
    PublishError,
    PublishOutcome,
    PublishRequest,
    register_adapter,
)

logger = logging.getLogger(__name__)


YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_REQUIRED_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


@register_adapter("youtube")
class YouTubeAdapter(PlatformAdapter):
    is_real = True
    requires_credential = True

    def upload(self, req: PublishRequest) -> PublishOutcome:
        settings = get_settings()
        if not settings.google_client_id or not settings.google_client_secret:
            # 缺平台凭证（dev 环境）：不抛异常，告诉用户去 .env 配
            return PublishOutcome(
                ok=False,
                status="failed",
                error=(
                    "YouTube adapter 需要 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET；"
                    "请在 .env 配置后重试，或把 plan.platform 切到 'dry-run'"
                ),
            )

        cred = req.credential or {}
        access_token = cred.get("access_token")
        refresh_token = cred.get("refresh_token")
        scopes = cred.get("scope") or []
        if not isinstance(scopes, list):
            scopes = []

        if not access_token:
            return PublishOutcome(
                ok=False,
                status="failed",
                error="user has not authorized YouTube; click 「绑定 YouTube」 to start OAuth",
            )

        if YOUTUBE_REQUIRED_SCOPE not in scopes:
            return PublishOutcome(
                ok=False,
                status="failed",
                error=(
                    f"current YouTube credential lacks required scope "
                    f"'{YOUTUBE_REQUIRED_SCOPE}'; re-authorize to grant upload permission"
                ),
            )

        if not req.render_url:
            return PublishOutcome(
                ok=False,
                status="failed",
                error="render_url empty; cannot upload",
            )

        # token 过期主动刷新（expires_at 由 caller 拼好放 cred.expires_at）
        expires_at = cred.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at < datetime.now(tz=timezone.utc):
            try:
                refreshed = _refresh_youtube_token(refresh_token, settings)
            except Exception as exc:  # pragma: no cover - 真实网络
                raise PublishError(f"youtube token refresh failed: {exc}") from exc
            if refreshed:
                access_token = refreshed["access_token"]
                cred["access_token"] = access_token
                cred["expires_at"] = refreshed["expires_at"]

        # 安全闸门（Track-02）：除非 plan.confirm_real_publish=true，否则不真发。
        # executor 把该列从 publish_plans 直接读出后透传到 req.confirm_real_publish。
        if not req.confirm_real_publish:
            ext_id = f"youtube-pending-{req.plan_id[:8]}-{int(time.time())}"
            logger.info(
                "youtube adapter safety gate: not actually uploading plan=%s; "
                "toggle plan.confirm_real_publish=true to trigger real upload",
                req.plan_id,
            )
            return PublishOutcome(
                ok=True,
                external_id=ext_id,
                external_url=f"https://youtube.com/watch?v={ext_id}",
                status="published",
                published_at=datetime.now(tz=timezone.utc),
                meta={
                    "platform": "youtube",
                    "safety_gate": "skipped real upload (toggle plan.confirm_real_publish=true to enable)",
                    "title": req.title,
                    "tags": req.tags,
                },
                credential_update=(
                    {
                        "access_token": cred["access_token"],
                        "expires_at": cred["expires_at"],
                    }
                    if cred.get("expires_at")
                    else None
                ),
            )

        # ── 真发路径（v1：单次 multipart upload；resumable 留 v2） ─────────
        # 先把 render_url 下载到内存（最大 100MB；对 1080p 30s 足够）
        try:
            resp = requests.get(req.render_url, timeout=120, stream=True)
            resp.raise_for_status()
            video_bytes = resp.content
        except requests.RequestException as exc:
            raise PublishError(f"download render_url failed: {exc}") from exc

        snippet: dict[str, Any] = {
            "title": (req.title or "Untitled")[:100],
            "description": req.description or "",
            "tags": req.tags[:30],
        }
        status_part = {"privacyStatus": "private"}  # v1 默认 private 安全
        body = {"snippet": snippet, "status": status_part}

        files = {
            "metadata": (
                "metadata.json",
                json.dumps(body, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=UTF-8",
            ),
            "media": ("video.mp4", video_bytes, "video/mp4"),
        }
        try:
            yt_resp = requests.post(
                YOUTUBE_UPLOAD_URL,
                params={"part": "snippet,status"},
                headers={"Authorization": f"Bearer {access_token}"},
                files=files,
                timeout=600,
            )
        except requests.RequestException as exc:
            raise PublishError(f"youtube upload http error: {exc}") from exc

        if yt_resp.status_code >= 500:
            raise PublishError(
                f"youtube upload 5xx: {yt_resp.status_code} {yt_resp.text[:200]}"
            )
        if yt_resp.status_code >= 400:
            return PublishOutcome(
                ok=False,
                status="failed",
                error=f"youtube http {yt_resp.status_code}: {yt_resp.text[:300]}",
            )

        try:
            payload = yt_resp.json()
        except json.JSONDecodeError:
            return PublishOutcome(
                ok=False, status="failed", error="youtube returned non-json"
            )

        video_id = str(payload.get("id") or "")
        if not video_id:
            return PublishOutcome(
                ok=False,
                status="failed",
                error=f"youtube response missing id: {yt_resp.text[:300]}",
            )
        return PublishOutcome(
            ok=True,
            external_id=video_id,
            external_url=f"https://youtube.com/watch?v={video_id}",
            status="published",
            published_at=datetime.now(tz=timezone.utc),
            meta={"platform": "youtube", "raw": payload},
            credential_update=(
                {"access_token": access_token, "expires_at": cred.get("expires_at")}
            ),
        )


def _refresh_youtube_token(
    refresh_token: Optional[str], settings: Any
) -> Optional[dict[str, Any]]:
    """用 refresh_token 拿新 access_token。返 {access_token, expires_at}。"""
    if not refresh_token:
        return None
    resp = requests.post(
        YOUTUBE_OAUTH_TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise PublishError(
            f"youtube refresh http {resp.status_code}: {resp.text[:200]}"
        )
    payload = resp.json()
    expires_in = int(payload.get("expires_in") or 3600)
    return {
        "access_token": payload["access_token"],
        "expires_at": datetime.now(tz=timezone.utc).replace(microsecond=0)
        + _seconds_delta(expires_in),
    }


def _seconds_delta(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


__all__ = ["YouTubeAdapter"]
