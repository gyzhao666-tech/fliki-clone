"""生产元数据查询路由（数据模型扩展 v1）。

提供按 run_id / file_id 查 shots / renders / reviews / publish_plans / metrics / versions
的只读端点，以及发布计划的 CRUD 与版本标签管理。

设计：
- 端点都先 ensure run / file owner 鉴权（与 pipelines.py 一致）
- 查询走原生 SQL（避免 ORM 异步 session 在 sync engine 上下文里来回切换的复杂度）
- 响应字段名与新表列名一致；前端直接消费
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.deps import CurrentUser
from app.models.production import PUBLISH_STATUSES, REVIEW_SEVERITIES
from app.services.publishing import (
    PublishError,
    execute_publish_plan as _execute_publish_plan,
    list_supported_platforms as _list_supported_platforms,
)
from app.services.publishing import credentials as _publish_creds
from app.services.publishing import oauth as _publish_oauth


router = APIRouter(prefix="/production", tags=["Production"])


# ── helpers ─────────────────────────────────────────────────────────────────


def _engine():
    return create_engine(get_settings().database_url_sync)


def _ensure_run_owner(run_id: str, user_id: str) -> Optional[str]:
    """返回 run.file_id；不存在 404；非本人 403。"""

    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT user_id, file_id FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    if row[0] and row[0] != user_id:
        raise HTTPException(status_code=403, detail="not your run")
    return row[1]


def _ensure_file_owner(file_id: str, user_id: str) -> None:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT user_id FROM files WHERE id = :id"),
            {"id": file_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="file not found")
    if row[0] and row[0] != user_id:
        raise HTTPException(status_code=403, detail="not your file")


# ── schemas ─────────────────────────────────────────────────────────────────


class ShotOut(BaseModel):
    id: str
    index: int
    duration_s: float
    narration: Optional[str] = None
    visual: Optional[str] = None
    camera: Optional[str] = None
    enhanced_prompt: Optional[str] = None
    negative_prompt: Optional[str] = None
    aspect_ratio: Optional[str] = None
    focus_character: Optional[str] = None
    keyframe_url: Optional[str] = None
    keyframe_provider: Optional[str] = None
    keyframe_model: Optional[str] = None
    keyframe_size: Optional[str] = None
    keyframe_error: Optional[str] = None
    video_url: Optional[str] = None
    video_provider: Optional[str] = None
    video_model: Optional[str] = None
    video_mode: Optional[str] = None
    video_cost_usd: float = 0.0
    video_duration_ms: int = 0
    video_error: Optional[str] = None


class ShotListOut(BaseModel):
    id: str
    run_id: str
    file_id: Optional[str] = None
    title: Optional[str] = None
    hook: Optional[str] = None
    script: Optional[str] = None
    cta: Optional[str] = None
    aspect_ratio: Optional[str] = None
    topic: Optional[dict[str, Any]] = None
    style_board: Optional[dict[str, Any]] = None
    character_cards: Optional[list[dict[str, Any]]] = None
    shots: list[ShotOut] = Field(default_factory=list)


class RenderOut(BaseModel):
    id: str
    run_id: str
    file_id: Optional[str] = None
    aspect_ratio: str
    aspect_fit: Optional[str] = None
    is_primary: bool
    url: Optional[str] = None
    silent_video_url: Optional[str] = None
    subtitle_url: Optional[str] = None
    narration_url: Optional[str] = None
    duration_s: float = 0.0
    shot_count: int = 0
    file_size_bytes: Optional[int] = None
    muxed: bool = False
    burned_in_subtitles: bool = False
    looped_video: bool = False
    status: str = "succeeded"
    warning: Optional[str] = None
    created_at: datetime


class ReviewOut(BaseModel):
    id: str
    run_id: str
    step_id: Optional[str] = None
    severity: str
    area: str
    message: str
    meta: Optional[dict[str, Any]] = None
    created_at: datetime


class PublishPlanOut(BaseModel):
    id: str
    file_id: str
    run_id: Optional[str] = None
    render_id: Optional[str] = None
    platform: str
    status: str
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    external_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    cover_url: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MetricOut(BaseModel):
    id: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    file_id: Optional[str] = None
    kind: str
    value_num: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    captured_at: datetime


class VersionOut(BaseModel):
    id: str
    file_id: str
    run_id: str
    label: str
    primary_render_id: Optional[str] = None
    is_published: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ── shot_lists & shots ─────────────────────────────────────────────────────


@router.get("/runs/{run_id}/shot-list", response_model=Optional[ShotListOut])
async def get_run_shot_list(run_id: str, current_user: CurrentUser) -> Optional[ShotListOut]:
    _ensure_run_owner(run_id, current_user.id)
    with _engine().connect() as conn:
        sl = conn.execute(
            text(
                "SELECT id, run_id, file_id, title, hook, script, cta, aspect_ratio, "
                "topic_json, style_board_json, character_cards_json "
                "FROM shot_lists WHERE run_id = :rid LIMIT 1"
            ),
            {"rid": run_id},
        ).fetchone()
        if not sl:
            return None

        shots = conn.execute(
            text(
                "SELECT id, index, duration_s, narration, visual, camera, enhanced_prompt, "
                "negative_prompt, aspect_ratio, focus_character, keyframe_url, keyframe_provider, "
                "keyframe_model, keyframe_size, keyframe_error, video_url, video_provider, "
                "video_model, video_mode, video_cost_usd, video_duration_ms, video_error "
                "FROM shots WHERE shot_list_id = :slid ORDER BY index ASC"
            ),
            {"slid": sl[0]},
        ).fetchall()

    return ShotListOut(
        id=sl[0],
        run_id=sl[1],
        file_id=sl[2],
        title=sl[3],
        hook=sl[4],
        script=sl[5],
        cta=sl[6],
        aspect_ratio=sl[7],
        topic=sl[8],
        style_board=sl[9],
        character_cards=sl[10],
        shots=[
            ShotOut(
                id=s[0], index=int(s[1]), duration_s=float(s[2] or 0.0),
                narration=s[3], visual=s[4], camera=s[5],
                enhanced_prompt=s[6], negative_prompt=s[7], aspect_ratio=s[8],
                focus_character=s[9], keyframe_url=s[10], keyframe_provider=s[11],
                keyframe_model=s[12], keyframe_size=s[13], keyframe_error=s[14],
                video_url=s[15], video_provider=s[16], video_model=s[17],
                video_mode=s[18], video_cost_usd=float(s[19] or 0.0),
                video_duration_ms=int(s[20] or 0), video_error=s[21],
            )
            for s in shots
        ],
    )


# ── renders ────────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/renders", response_model=list[RenderOut])
async def list_run_renders(run_id: str, current_user: CurrentUser) -> list[RenderOut]:
    _ensure_run_owner(run_id, current_user.id)
    return _query_renders(where="run_id = :id", params={"id": run_id})


@router.get("/files/{file_id}/renders", response_model=list[RenderOut])
async def list_file_renders(file_id: str, current_user: CurrentUser) -> list[RenderOut]:
    _ensure_file_owner(file_id, current_user.id)
    return _query_renders(where="file_id = :id", params={"id": file_id})


def _query_renders(*, where: str, params: dict[str, Any]) -> list[RenderOut]:
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, run_id, file_id, aspect_ratio, aspect_fit, is_primary, url, "
                "silent_video_url, subtitle_url, narration_url, duration_s, shot_count, "
                "file_size_bytes, muxed, burned_in_subtitles, looped_video, status, warning, "
                "created_at FROM renders WHERE " + where + " ORDER BY is_primary DESC, "
                "aspect_ratio ASC, created_at DESC"
            ),
            params,
        ).fetchall()
    return [
        RenderOut(
            id=r[0], run_id=r[1], file_id=r[2], aspect_ratio=r[3], aspect_fit=r[4],
            is_primary=bool(r[5]), url=r[6], silent_video_url=r[7], subtitle_url=r[8],
            narration_url=r[9], duration_s=float(r[10] or 0.0), shot_count=int(r[11] or 0),
            file_size_bytes=int(r[12]) if r[12] is not None else None,
            muxed=bool(r[13]), burned_in_subtitles=bool(r[14]), looped_video=bool(r[15]),
            status=r[16] or "succeeded", warning=r[17], created_at=r[18],
        )
        for r in rows
    ]


# ── reviews ─────────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/reviews", response_model=list[ReviewOut])
async def list_run_reviews(run_id: str, current_user: CurrentUser) -> list[ReviewOut]:
    _ensure_run_owner(run_id, current_user.id)
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, run_id, step_id, severity, area, message, meta_json, created_at "
                "FROM reviews WHERE run_id = :rid "
                "ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 "
                "ELSE 2 END, created_at ASC"
            ),
            {"rid": run_id},
        ).fetchall()
    return [
        ReviewOut(
            id=r[0], run_id=r[1], step_id=r[2], severity=r[3], area=r[4],
            message=r[5], meta=r[6], created_at=r[7],
        )
        for r in rows
    ]


# ── metrics ─────────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}/metrics", response_model=list[MetricOut])
async def list_run_metrics(
    run_id: str, current_user: CurrentUser, kind: Optional[str] = None
) -> list[MetricOut]:
    _ensure_run_owner(run_id, current_user.id)
    where = "run_id = :rid"
    params: dict[str, Any] = {"rid": run_id}
    if kind:
        where += " AND kind = :kind"
        params["kind"] = kind
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, run_id, step_id, file_id, kind, value_num, value_text, unit, "
                "captured_at FROM metrics WHERE " + where + " ORDER BY captured_at ASC"
            ),
            params,
        ).fetchall()
    return [_metric_row_to_out(r) for r in rows]


def _metric_row_to_out(r) -> MetricOut:
    return MetricOut(
        id=r[0], run_id=r[1], step_id=r[2], file_id=r[3], kind=r[4],
        value_num=float(r[5]) if r[5] is not None else None, value_text=r[6],
        unit=r[7], captured_at=r[8],
    )


# ── publish_plans ───────────────────────────────────────────────────────────


class PublishPlanIn(BaseModel):
    file_id: str
    render_id: Optional[str] = None
    run_id: Optional[str] = None
    platform: str
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    cover_url: Optional[str] = None
    scheduled_at: Optional[datetime] = None


class PublishPlanPatch(BaseModel):
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    external_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    cover_url: Optional[str] = None
    render_id: Optional[str] = None
    error: Optional[str] = None


@router.get("/files/{file_id}/publish-plans", response_model=list[PublishPlanOut])
async def list_publish_plans(
    file_id: str, current_user: CurrentUser
) -> list[PublishPlanOut]:
    _ensure_file_owner(file_id, current_user.id)
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, file_id, run_id, render_id, platform, status, scheduled_at, "
                "published_at, external_id, title, description, tags_json, cover_url, error, "
                "created_at, updated_at FROM publish_plans WHERE file_id = :fid "
                "ORDER BY created_at DESC"
            ),
            {"fid": file_id},
        ).fetchall()
    return [_plan_row_to_out(r) for r in rows]


@router.post(
    "/publish-plans", response_model=PublishPlanOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_publish_plan(
    body: PublishPlanIn, current_user: CurrentUser
) -> PublishPlanOut:
    _ensure_file_owner(body.file_id, current_user.id)
    if body.render_id:
        _ensure_render_in_file(body.render_id, body.file_id)
    plan_id = str(uuid.uuid4())
    with _engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO publish_plans (id, file_id, run_id, render_id, platform, "
                "status, scheduled_at, title, description, tags_json, cover_url) VALUES "
                "(:id, :fid, :rid, :reid, :pf, 'draft', :sa, :title, :desc, "
                "CAST(:tags AS JSON), :cover)"
            ),
            {
                "id": plan_id,
                "fid": body.file_id,
                "rid": body.run_id,
                "reid": body.render_id,
                "pf": body.platform,
                "sa": body.scheduled_at,
                "title": body.title,
                "desc": body.description,
                "tags": _json_list(body.tags),
                "cover": body.cover_url,
            },
        )
    return _load_plan_or_404(plan_id)


@router.patch("/publish-plans/{plan_id}", response_model=PublishPlanOut)
async def patch_publish_plan(
    plan_id: str, body: PublishPlanPatch, current_user: CurrentUser
) -> PublishPlanOut:
    _ensure_publish_plan_owner(plan_id, current_user.id)

    if body.status is not None and body.status not in PUBLISH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status; must be one of {PUBLISH_STATUSES}",
        )

    sets: list[str] = []
    params: dict[str, Any] = {"id": plan_id}
    for field, col, val in (
        ("status", "status", body.status),
        ("scheduled_at", "scheduled_at", body.scheduled_at),
        ("published_at", "published_at", body.published_at),
        ("external_id", "external_id", body.external_id),
        ("title", "title", body.title),
        ("description", "description", body.description),
        ("cover_url", "cover_url", body.cover_url),
        ("render_id", "render_id", body.render_id),
        ("error", "error", body.error),
    ):
        if val is not None:
            sets.append(f"{col} = :{field}")
            params[field] = val
    if body.tags is not None:
        sets.append("tags_json = CAST(:tags AS JSON)")
        params["tags"] = _json_list(body.tags)
    if not sets:
        return _load_plan_or_404(plan_id)
    sets.append("updated_at = NOW()")
    with _engine().begin() as conn:
        conn.execute(
            text("UPDATE publish_plans SET " + ", ".join(sets) + " WHERE id = :id"),
            params,
        )
    return _load_plan_or_404(plan_id)


@router.delete("/publish-plans/{plan_id}")
async def delete_publish_plan(
    plan_id: str, current_user: CurrentUser
) -> dict[str, bool]:
    _ensure_publish_plan_owner(plan_id, current_user.id)
    with _engine().begin() as conn:
        conn.execute(text("DELETE FROM publish_plans WHERE id = :id"), {"id": plan_id})
    return {"deleted": True}


def _ensure_render_in_file(render_id: str, file_id: str) -> None:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT file_id FROM renders WHERE id = :id"),
            {"id": render_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="render not found")
    if row[0] and row[0] != file_id:
        raise HTTPException(status_code=400, detail="render not in this file")


def _ensure_publish_plan_owner(plan_id: str, user_id: str) -> None:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT f.user_id FROM publish_plans p JOIN files f ON f.id = p.file_id "
                "WHERE p.id = :id"
            ),
            {"id": plan_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="publish plan not found")
    if row[0] and row[0] != user_id:
        raise HTTPException(status_code=403, detail="not your publish plan")


def _load_plan_or_404(plan_id: str) -> PublishPlanOut:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, file_id, run_id, render_id, platform, status, scheduled_at, "
                "published_at, external_id, title, description, tags_json, cover_url, error, "
                "created_at, updated_at FROM publish_plans WHERE id = :id"
            ),
            {"id": plan_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="publish plan not found")
    return _plan_row_to_out(row)


def _plan_row_to_out(r) -> PublishPlanOut:
    tags = r[11] if isinstance(r[11], list) else None
    return PublishPlanOut(
        id=r[0], file_id=r[1], run_id=r[2], render_id=r[3], platform=r[4], status=r[5],
        scheduled_at=r[6], published_at=r[7], external_id=r[8], title=r[9],
        description=r[10], tags=tags, cover_url=r[12], error=r[13],
        created_at=r[14], updated_at=r[15],
    )


def _json_list(value: Optional[list[str]]) -> str:
    import json as _json

    return _json.dumps(value if value is not None else [], ensure_ascii=False)


# ── versions ────────────────────────────────────────────────────────────────


class VersionIn(BaseModel):
    file_id: str
    run_id: str
    label: str
    primary_render_id: Optional[str] = None
    notes: Optional[str] = None
    is_published: bool = False


@router.get("/files/{file_id}/versions", response_model=list[VersionOut])
async def list_file_versions(
    file_id: str, current_user: CurrentUser
) -> list[VersionOut]:
    _ensure_file_owner(file_id, current_user.id)
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, file_id, run_id, label, primary_render_id, is_published, "
                "notes, created_at, updated_at FROM versions WHERE file_id = :fid "
                "ORDER BY is_published DESC, created_at DESC"
            ),
            {"fid": file_id},
        ).fetchall()
    return [_version_row_to_out(r) for r in rows]


@router.post(
    "/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED
)
async def create_version(
    body: VersionIn, current_user: CurrentUser
) -> VersionOut:
    _ensure_file_owner(body.file_id, current_user.id)
    _ensure_run_owner(body.run_id, current_user.id)
    if body.primary_render_id:
        _ensure_render_in_file(body.primary_render_id, body.file_id)
    vid = str(uuid.uuid4())
    with _engine().begin() as conn:
        # is_published 互斥：同一 file_id 只允许一个 published 版本
        if body.is_published:
            conn.execute(
                text(
                    "UPDATE versions SET is_published = false, updated_at = NOW() "
                    "WHERE file_id = :fid AND is_published = true"
                ),
                {"fid": body.file_id},
            )
        conn.execute(
            text(
                "INSERT INTO versions (id, file_id, run_id, label, primary_render_id, "
                "is_published, notes) VALUES (:id, :fid, :rid, :lab, :pr, :pub, :notes)"
            ),
            {
                "id": vid,
                "fid": body.file_id,
                "rid": body.run_id,
                "lab": body.label,
                "pr": body.primary_render_id,
                "pub": body.is_published,
                "notes": body.notes,
            },
        )
    return _load_version_or_404(vid)


@router.post("/versions/{version_id}/publish", response_model=VersionOut)
async def set_version_published(
    version_id: str, current_user: CurrentUser
) -> VersionOut:
    file_id = _ensure_version_owner(version_id, current_user.id)
    with _engine().begin() as conn:
        conn.execute(
            text(
                "UPDATE versions SET is_published = false, updated_at = NOW() "
                "WHERE file_id = :fid AND is_published = true"
            ),
            {"fid": file_id},
        )
        conn.execute(
            text(
                "UPDATE versions SET is_published = true, updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"id": version_id},
        )
    return _load_version_or_404(version_id)


@router.delete("/versions/{version_id}")
async def delete_version(
    version_id: str, current_user: CurrentUser
) -> dict[str, bool]:
    _ensure_version_owner(version_id, current_user.id)
    with _engine().begin() as conn:
        conn.execute(text("DELETE FROM versions WHERE id = :id"), {"id": version_id})
    return {"deleted": True}


def _ensure_version_owner(version_id: str, user_id: str) -> str:
    """返回 file_id；不存在 404；非本人 403。"""

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT v.file_id, f.user_id FROM versions v JOIN files f ON f.id = v.file_id "
                "WHERE v.id = :id"
            ),
            {"id": version_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="version not found")
    if row[1] and row[1] != user_id:
        raise HTTPException(status_code=403, detail="not your version")
    return row[0]


def _load_version_or_404(version_id: str) -> VersionOut:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, file_id, run_id, label, primary_render_id, is_published, "
                "notes, created_at, updated_at FROM versions WHERE id = :id"
            ),
            {"id": version_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="version not found")
    return _version_row_to_out(row)


def _version_row_to_out(r) -> VersionOut:
    return VersionOut(
        id=r[0], file_id=r[1], run_id=r[2], label=r[3], primary_render_id=r[4],
        is_published=bool(r[5]), notes=r[6], created_at=r[7], updated_at=r[8],
    )


# ── 发布执行器 v1 ────────────────────────────────────────────────────────────
# 1. POST /publish-plans/{id}/execute   触发执行（同步路径；celery 路径留 v2）
# 2. GET  /platforms                    列已注册 adapter（dry-run / youtube / bilibili / ...）
# 3. GET  /platforms/credentials        本人已绑平台凭证视图（access_token 不下发）
# 4. DELETE /platforms/{platform}/credentials  撤销凭证
# 5. POST /platforms/{platform}/oauth/start    返 OAuth 授权 URL
# 6. GET  /platforms/{platform}/oauth/callback OAuth provider 302 回到这里
#
# 安全：execute / oauth start 都需要登录；callback 不需要登录但必须验 state
# （state JWT 里带 user_id；防 CSRF）。


class PublishOutcomeOut(BaseModel):
    plan_id: str
    ok: bool
    status: str
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    error: Optional[str] = None
    plan: Optional[PublishPlanOut] = None


class PlatformOut(BaseModel):
    name: str
    is_real: bool
    requires_credential: bool


class CredentialOut(BaseModel):
    id: str
    user_id: str
    platform: str
    display_name: Optional[str] = None
    external_user_id: Optional[str] = None
    has_access_token: bool = False
    has_refresh_token: bool = False
    token_expires_at: Optional[datetime] = None
    scope: list[str] = Field(default_factory=list)
    status: str = "active"


class OAuthStartOut(BaseModel):
    authorize_url: str
    state: str


@router.post(
    "/publish-plans/{plan_id}/execute",
    response_model=PublishOutcomeOut,
)
async def execute_publish_plan_route(
    plan_id: str, current_user: CurrentUser
) -> PublishOutcomeOut:
    """触发发布执行；同步等 adapter 返回。

    返：执行结果 + 最新 plan 视图（status / external_id / error 已写入）。
    系统级异常（PublishError）翻成 502，让调用方决定是否重试 / 入 DLQ。
    """
    _ensure_publish_plan_owner(plan_id, current_user.id)

    try:
        outcome = _execute_publish_plan(plan_id, user_id=current_user.id)
    except PublishError as exc:
        # 系统级异常：进 DLQ + 返 502
        try:
            from app.services.pipeline import dlq as pipeline_dlq

            pipeline_dlq.push(
                task_name="publish.execute_plan",
                args=[plan_id],
                kwargs={"user_id": current_user.id},
                user_id=current_user.id,
                error=str(exc),
                run_id=None,
            )
        except Exception:  # pragma: no cover - DLQ 写失败也不破坏 502
            pass
        raise HTTPException(
            status_code=502,
            detail=f"publish system error (queued in DLQ): {exc}",
        )

    plan = _load_plan_or_404(plan_id)
    return PublishOutcomeOut(
        plan_id=plan_id,
        ok=outcome.ok,
        status=outcome.status,
        external_id=outcome.external_id,
        external_url=outcome.external_url,
        error=outcome.error,
        plan=plan,
    )


@router.get("/platforms", response_model=list[PlatformOut])
async def list_platforms(_: CurrentUser) -> list[PlatformOut]:
    """前端「绑定平台」面板：列所有已注册 adapter + 是否需要 OAuth。"""
    return [PlatformOut(**p) for p in _list_supported_platforms()]


@router.get("/platforms/credentials", response_model=list[CredentialOut])
async def list_credentials(current_user: CurrentUser) -> list[CredentialOut]:
    payloads = _publish_creds.list_user_credentials(current_user.id)
    return [
        CredentialOut(
            id=c.id,
            user_id=c.user_id,
            platform=c.platform,
            display_name=c.display_name,
            external_user_id=c.external_user_id,
            has_access_token=bool(c.access_token),
            has_refresh_token=bool(c.refresh_token),
            token_expires_at=c.token_expires_at,
            scope=c.scope,
            status=c.status,
        )
        for c in payloads
    ]


@router.delete("/platforms/{platform}/credentials")
async def revoke_credentials(
    platform: str, current_user: CurrentUser
) -> dict[str, bool]:
    deleted = _publish_creds.revoke_credential(current_user.id, platform)
    return {"deleted": deleted}


@router.post(
    "/platforms/{platform}/oauth/start", response_model=OAuthStartOut
)
async def start_platform_oauth(
    platform: str, current_user: CurrentUser
) -> OAuthStartOut:
    if platform != "youtube":
        # v1 仅 youtube 走 OAuth；其他平台返 400 + 引导用户用 dry-run
        raise HTTPException(
            status_code=400,
            detail=(
                f"OAuth not supported for platform '{platform}'; "
                "v1 only supports 'youtube'. Use 'dry-run' or 'bilibili' (manual upload) instead."
            ),
        )
    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=400,
            detail=(
                "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured in .env; "
                "cannot start YouTube OAuth. Add them and restart backend."
            ),
        )
    state = _publish_oauth.build_state(current_user.id, "youtube")
    return OAuthStartOut(
        authorize_url=_publish_oauth.build_youtube_authorize_url(state),
        state=state,
    )


@router.get("/platforms/{platform}/oauth/callback")
async def platform_oauth_callback(platform: str, code: str = "", state: str = ""):
    """OAuth provider 302 回到这里；不要求登录（只验 state JWT）。

    成功后 302 到 frontend `/app/settings/integrations?platform=...&result=ok`；
    失败 302 到 `?result=error&detail=...`。
    """
    settings = get_settings()
    fail_redirect = (
        f"{settings.frontend_url.rstrip('/')}"
        f"/app/settings/integrations?platform={platform}&result=error&detail="
    )
    if not code:
        return RedirectResponse(
            url=fail_redirect + "missing_code", status_code=302
        )
    if not state:
        return RedirectResponse(
            url=fail_redirect + "missing_state", status_code=302
        )
    if platform != "youtube":
        return RedirectResponse(
            url=fail_redirect + "unsupported_platform", status_code=302
        )

    try:
        result = _publish_oauth.complete_youtube_oauth(code=code, state=state)
    except Exception as exc:
        return RedirectResponse(
            url=fail_redirect + str(exc)[:200], status_code=302
        )

    return RedirectResponse(
        url=(
            f"{settings.frontend_url.rstrip('/')}"
            f"/app/settings/integrations?platform={result['platform']}&result=ok"
        ),
        status_code=302,
    )


__all__ = ["router", "REVIEW_SEVERITIES"]
