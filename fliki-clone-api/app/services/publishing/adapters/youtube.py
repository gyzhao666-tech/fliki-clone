"""YouTube adapter（真发，依赖用户 OAuth + GOOGLE_CLIENT_ID/SECRET）。

设计取舍
-------
- 真实端点：`POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable`
  → 拿 session uri；之后 PUT session uri 分片上传
- 用户配 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` + 走 OAuth 拿 access/refresh token
  + scope 必须含 `https://www.googleapis.com/auth/youtube.upload`
- 缺凭证 / scope 不足时返 `PublishOutcome(ok=False, error=...)`，不抛异常 → executor 写
  `plan.status='failed' + plan.error=...`，前端显示「YouTube 未授权 / scope 不足」
- 安全闸门：除非 `req.confirm_real_publish=True` 否则不真发，返 mock external_id
  （Track-02 已把这个开关从 `meta_json` 提到独立列；req.confirm_real_publish 由 executor 透传）

Track-13：分片上传（chunked PUT）
--------------------------------
v1 用 multipart 一把发，1080p / 60s+ 视频在 60s HTTP timeout 下经常断流；改 resumable
upload v2：
1. `_initiate_resumable_upload` POST 拿 session uri（带 X-Upload-Content-Length 头预声明）
2. `_chunked_put` 把 video_bytes 切成 8 MiB 片，每片带 `Content-Range: bytes X-Y/total` PUT；
   返 308 = 滚下一片；最后片返 200/201 + JSON `{id: video_id}`
3. 每片完调一次 `progress_cb({phase, bytes_uploaded, total, percent, chunk_index, chunk_count})`
   让 executor 把进度落 `publish_plans.meta_json` + 推 SSE `upload_progress` 事件
4. 5xx / 408 / 429 → 指数退避重试（每片最多 3 次）；4xx 其它 → 立刻判失败返 ok=False

参考
----
https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

import requests

from app.config import get_settings

from .base import (
    PlatformAdapter,
    ProgressCb,
    PublishError,
    PublishOutcome,
    PublishRequest,
    register_adapter,
)

logger = logging.getLogger(__name__)


YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_REQUIRED_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

# 分片大小：YouTube 推荐 256 KiB 的整数倍；8 MiB 在 30-60s 网段下落到 1-2s/片，
# 即每片 1-2s 一次 SSE 推进度，前端进度条手感顺滑且重传成本可控
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
# 单片最多重试 3 次（不含首发）；对 5xx/408/429 指数退避 1s/2s/4s
MAX_RETRIES_PER_CHUNK = 3
# 首请求建立 session + 单片 PUT 的 HTTP 总超时
SESSION_TIMEOUT = 60.0
CHUNK_TIMEOUT = 120.0


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

        # ── 真发路径（Track-13：resumable upload + 8 MiB chunked PUT） ─────────
        # 1) 下载 render_url 到内存（最大 ~500 MB；执行机内存够，YouTube 单视频 256GB
        #    上限远超本期承载范围；如果 stream 进 ffmpeg 处理留 v3 再说）
        try:
            video_bytes = _download_render(req.render_url, progress_cb=req.progress_cb)
        except requests.RequestException as exc:
            raise PublishError(f"download render_url failed: {exc}") from exc

        snippet: dict[str, Any] = {
            "title": (req.title or "Untitled")[:100],
            "description": req.description or "",
            "tags": req.tags[:30],
        }
        status_part = {"privacyStatus": "private"}  # v1 默认 private 安全
        body = {"snippet": snippet, "status": status_part}

        total_bytes = len(video_bytes)
        # 2) initiate session
        try:
            session_uri = _initiate_resumable_upload(
                access_token=access_token,
                metadata=body,
                total_bytes=total_bytes,
            )
        except PublishError:
            raise
        except requests.RequestException as exc:
            raise PublishError(f"youtube initiate upload failed: {exc}") from exc

        # 3) chunked PUT
        try:
            video_id = _chunked_put(
                upload_url=session_uri,
                video_bytes=video_bytes,
                chunk_size=DEFAULT_CHUNK_SIZE,
                progress_cb=req.progress_cb,
            )
        except PublishError:
            raise
        except requests.RequestException as exc:
            raise PublishError(f"youtube chunked upload failed: {exc}") from exc

        return PublishOutcome(
            ok=True,
            external_id=video_id,
            external_url=f"https://youtube.com/watch?v={video_id}",
            status="published",
            published_at=datetime.now(tz=timezone.utc),
            meta={
                "platform": "youtube",
                "upload_mode": "resumable_chunked",
                "chunk_size": DEFAULT_CHUNK_SIZE,
                "total_bytes": total_bytes,
            },
            credential_update=(
                {"access_token": access_token, "expires_at": cred.get("expires_at")}
            ),
        )


# ── helpers ─────────────────────────────────────────────────────────────────


def _download_render(
    url: str, *, progress_cb: Optional[ProgressCb]
) -> bytes:
    """从 render_url 下到内存。下载阶段也回调 progress_cb（phase=downloading），
    让前端进度条不在 0% 卡住等 chunked PUT 开始。
    """

    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    # 下载只发一次进度（开始 + 完成）；中间不分片以避免对 cb 频繁触发
    if progress_cb:
        try:
            progress_cb(
                {
                    "phase": "downloading",
                    "bytes_uploaded": 0,
                    "total": int(resp.headers.get("Content-Length") or 0),
                    "percent": 0.0,
                    "chunk_index": -1,
                    "chunk_count": 0,
                }
            )
        except Exception:  # pragma: no cover - cb 故障不阻断
            logger.exception("progress_cb downloading start failed")

    data = resp.content
    if progress_cb:
        try:
            progress_cb(
                {
                    "phase": "downloading",
                    "bytes_uploaded": len(data),
                    "total": len(data),
                    "percent": 100.0,
                    "chunk_index": -1,
                    "chunk_count": 0,
                }
            )
        except Exception:  # pragma: no cover
            logger.exception("progress_cb downloading complete failed")
    return data


def _initiate_resumable_upload(
    *, access_token: str, metadata: dict[str, Any], total_bytes: int
) -> str:
    """POST 拿 session uri；返 Location 头。

    任何 4xx/5xx 都翻成 PublishError（系统级失败 → DLQ）；返 200 但缺 Location 也判系统级失败。
    """

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(total_bytes),
    }
    resp = requests.post(
        YOUTUBE_UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers=headers,
        data=json.dumps(metadata, ensure_ascii=False).encode("utf-8"),
        timeout=SESSION_TIMEOUT,
    )
    if resp.status_code >= 500:
        raise PublishError(
            f"youtube initiate 5xx: {resp.status_code} {resp.text[:200]}"
        )
    if resp.status_code >= 400:
        raise PublishError(
            f"youtube initiate http {resp.status_code}: {resp.text[:300]}"
        )
    location = resp.headers.get("Location")
    if not location:
        raise PublishError(
            "youtube initiate response missing Location header (resumable session uri)"
        )
    return location


def _chunked_put(
    *,
    upload_url: str,
    video_bytes: bytes,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_cb: Optional[ProgressCb] = None,
    sleeper: Any = time.sleep,
) -> str:
    """按 chunk_size 切片 PUT；返 video_id（最后一片成功响应里的 `id`）。

    `sleeper` 仅供测试注入（默认 time.sleep）。
    """

    total = len(video_bytes)
    if total == 0:
        raise PublishError("video bytes empty; nothing to upload")

    # 计算总片数（最后一片可能不足 chunk_size）
    chunk_count = (total + chunk_size - 1) // chunk_size

    bytes_uploaded = 0
    for chunk_index in range(chunk_count):
        start = chunk_index * chunk_size
        end_inclusive = min(start + chunk_size, total) - 1
        chunk = video_bytes[start : end_inclusive + 1]

        attempt = 0
        while True:
            attempt += 1
            headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end_inclusive}/{total}",
            }
            try:
                resp = requests.put(
                    upload_url,
                    headers=headers,
                    data=chunk,
                    timeout=CHUNK_TIMEOUT,
                )
            except requests.RequestException as exc:
                # 网络层异常按可重试 5xx 处理
                if attempt > MAX_RETRIES_PER_CHUNK:
                    raise PublishError(
                        f"youtube chunk put network error chunk={chunk_index} "
                        f"attempt={attempt}: {exc}"
                    ) from exc
                _backoff(attempt, sleeper)
                continue

            status = resp.status_code

            if status in (200, 201):
                # 最后一片完成；body 是 video resource JSON
                bytes_uploaded = total
                _emit_progress(
                    progress_cb,
                    bytes_uploaded=bytes_uploaded,
                    total=total,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                )
                try:
                    payload = resp.json()
                except json.JSONDecodeError as exc:
                    raise PublishError(
                        f"youtube final chunk returned non-json: {resp.text[:200]}"
                    ) from exc
                video_id = str(payload.get("id") or "")
                if not video_id:
                    raise PublishError(
                        f"youtube final chunk missing id: {resp.text[:300]}"
                    )
                return video_id

            if status == 308:
                # 该片成功；继续下一片
                bytes_uploaded = end_inclusive + 1
                _emit_progress(
                    progress_cb,
                    bytes_uploaded=bytes_uploaded,
                    total=total,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                )
                break  # 退出 retry 循环 → 进入下一 chunk_index

            if status in (408, 429) or status >= 500:
                if attempt > MAX_RETRIES_PER_CHUNK:
                    raise PublishError(
                        f"youtube chunk put http {status} chunk={chunk_index} "
                        f"attempt={attempt}: {resp.text[:200]}"
                    )
                _backoff(attempt, sleeper)
                continue

            # 其它 4xx：不可恢复 → 系统级失败让 caller 入 DLQ
            raise PublishError(
                f"youtube chunk put http {status} chunk={chunk_index}: "
                f"{resp.text[:300]}"
            )

    raise PublishError(
        f"youtube chunked upload exhausted chunks without final 200 "
        f"(uploaded {bytes_uploaded}/{total})"
    )


def _emit_progress(
    progress_cb: Optional[ProgressCb],
    *,
    bytes_uploaded: int,
    total: int,
    chunk_index: int,
    chunk_count: int,
) -> None:
    if not progress_cb:
        return
    percent = (bytes_uploaded / total * 100.0) if total > 0 else 0.0
    try:
        progress_cb(
            {
                "phase": "uploading",
                "bytes_uploaded": bytes_uploaded,
                "total": total,
                "percent": round(percent, 2),
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
            }
        )
    except Exception:  # pragma: no cover - cb 故障不阻断上传
        logger.exception("progress_cb uploading chunk=%s failed", chunk_index)


def _backoff(attempt: int, sleeper: Any = time.sleep) -> None:
    """指数退避：1s / 2s / 4s（attempt 从 1 起）。
    用 sleeper 注入便于测试无 sleep。
    """

    delay = min(2 ** (attempt - 1), 8)
    try:
        sleeper(delay)
    except Exception:  # pragma: no cover
        pass


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


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MAX_RETRIES_PER_CHUNK",
    "YouTubeAdapter",
    "_chunked_put",
    "_initiate_resumable_upload",
]
