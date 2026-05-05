"""发布执行器主入口。

`execute_publish_plan(plan_id, *, user_id)`：
1. 加载 plan + 关联 render（renders.url 必填）
2. 选 adapter（按 plan.platform；未知降级 dry-run）
3. 加载 user × platform 凭证（如 adapter.requires_credential=True）
4. 拼 PublishRequest 调 adapter.upload()
5. 业务级失败（PublishOutcome.ok=False）→ plan.status='failed' + plan.error
6. 系统级异常（PublishError）→ DLQ + plan 不动（caller 决定 retry / discard）
7. 成功 → plan.status='published' + external_id + external_url + published_at
8. 触发 SSE 通知（publish_plan_state）

幂等性：v1 按 plan.status 简单判断——已是 published 时拒绝重发（caller 应先重置）。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

from . import credentials as creds
from .adapters import (
    PublishError,
    PublishOutcome,
    PublishRequest,
    get_adapter,
    list_supported_platforms,
)

logger = logging.getLogger(__name__)


def _engine():
    return create_engine(get_settings().database_url_sync)


def execute_publish_plan(plan_id: str, *, user_id: str) -> PublishOutcome:
    """执行单个发布计划。返 outcome 用于 caller 决策。"""
    plan_row = _load_plan(plan_id)
    if not plan_row:
        raise PublishError(f"plan {plan_id} not found")
    if plan_row["user_id"] and plan_row["user_id"] != user_id:
        raise PublishError(f"plan {plan_id} not owned by user {user_id}")

    if plan_row["status"] == "published":
        return PublishOutcome(
            ok=False,
            status="failed",
            error="plan already published; reset to draft before re-executing",
        )

    platform = str(plan_row["platform"] or "").strip().lower()
    adapter = get_adapter(platform)

    # 加载凭证（需要时）
    credential_dict: Optional[dict[str, Any]] = None
    if adapter.requires_credential:
        cred = creds.get_credential(user_id, platform)
        if cred is None:
            return _commit_outcome(
                plan_id=plan_id,
                outcome=PublishOutcome(
                    ok=False,
                    status="failed",
                    error=(
                        f"adapter '{platform}' requires OAuth credential; "
                        "click 「绑定 {platform}」 in UI to authorize"
                    ),
                ),
            )
        credential_dict = cred.to_adapter_input()

    # Track-13：分片上传进度回调；adapter 每完成一片调一次。
    # cb 把进度落 publish_plans.meta_json.upload_progress + 推 SSE upload_progress
    # 事件让前端进度条流畅；任一边 fail 都不阻断上传主流程。
    progress_cb = _make_progress_cb(plan_id)

    req = PublishRequest(
        plan_id=plan_id,
        user_id=user_id,
        platform=platform,
        file_id=plan_row["file_id"],
        run_id=plan_row["run_id"],
        render_id=plan_row["render_id"],
        render_url=plan_row["render_url"],
        cover_url=plan_row["cover_url"],
        title=plan_row["title"],
        description=plan_row["description"],
        tags=plan_row["tags"] or [],
        duration_s=plan_row["render_duration_s"] or 0.0,
        aspect_ratio=plan_row["render_aspect_ratio"],
        scheduled_at=plan_row["scheduled_at"],
        credential=credential_dict,
        idempotency_key=f"plan:{plan_id}",
        confirm_real_publish=bool(plan_row["confirm_real_publish"]),
        progress_cb=progress_cb,
    )

    try:
        outcome = adapter.upload(req)
    except PublishError:
        # 系统级异常：让 caller 入 DLQ；plan 状态保持原样
        raise
    except Exception as exc:  # pragma: no cover - 防御
        logger.exception("adapter %s raised", platform)
        raise PublishError(f"adapter {platform} raised: {exc}") from exc

    # 凭证回写（adapter 在内部 refresh 了 token）
    if outcome.credential_update and adapter.requires_credential:
        try:
            creds.update_after_publish(
                user_id=user_id,
                platform=platform,
                access_token=outcome.credential_update.get("access_token"),
                token_expires_at=outcome.credential_update.get("expires_at"),
            )
        except Exception:  # pragma: no cover - 凭证回写失败不阻断
            logger.exception(
                "credential update after publish failed user=%s platform=%s",
                user_id,
                platform,
            )

    return _commit_outcome(plan_id=plan_id, outcome=outcome)


def _commit_outcome(*, plan_id: str, outcome: PublishOutcome) -> PublishOutcome:
    """把 outcome 写回 publish_plans 行。"""
    new_status = (
        "published"
        if outcome.ok
        else ("failed" if outcome.status == "failed" else "scheduled")
    )
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE publish_plans
                   SET status = :st,
                       external_id = :eid,
                       published_at = :pat,
                       error = :err,
                       meta_json = COALESCE(CAST(:meta AS JSON), meta_json),
                       updated_at = NOW()
                 WHERE id = :id
                """
            ),
            {
                "id": plan_id,
                "st": new_status,
                "eid": outcome.external_id,
                "pat": outcome.published_at,
                "err": outcome.error,
                "meta": json.dumps(_outcome_meta(outcome), ensure_ascii=False)
                if outcome.meta or outcome.external_url
                else None,
            },
        )

    # 写一条 metric 便于后台聚合
    try:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO metrics (id, file_id, kind, value_num, value_text, unit)
                    SELECT :mid, p.file_id, :kind, :v, :vt, :u
                      FROM publish_plans p WHERE p.id = :pid
                    """
                ),
                {
                    "mid": str(uuid.uuid4()),
                    "pid": plan_id,
                    "kind": "publish_outcome",
                    "v": 1.0 if outcome.ok else 0.0,
                    "vt": outcome.status,
                    "u": "bool",
                },
            )
    except Exception:  # pragma: no cover - metric 失败不阻断
        logger.exception("metric write failed plan=%s", plan_id)

    return outcome


def _outcome_meta(outcome: PublishOutcome) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if outcome.meta:
        out.update(outcome.meta)
    if outcome.external_url:
        out["external_url"] = outcome.external_url
    return out


# ── Track-13：upload progress write-back + SSE 推送 ─────────────────────────


def _make_progress_cb(plan_id: str):
    """构造一个上传进度回调闭包。

    每次 adapter 完成一片就被调一次：
    1. read-modify-write `publish_plans.meta_json` 把 ``upload_progress`` 字段
       merge 进去（meta_json 是 JSON 而非 JSONB，没法用 `||` 直接合并）
    2. 推一条 SSE ``upload_progress`` 事件到 ``publish:plan:{plan_id}`` 频道
       让前端 hook 摘到 percent / bytes_uploaded 喂进度条

    任何写库 / 推 SSE 失败都仅记 warning：上传主流程必须不被进度回写挡住。
    """

    def _cb(info: dict[str, Any]) -> None:
        try:
            with _engine().begin() as conn:
                row = conn.execute(
                    text("SELECT meta_json FROM publish_plans WHERE id = :id"),
                    {"id": plan_id},
                ).fetchone()
                existing = (row[0] or {}) if row else {}
                if not isinstance(existing, dict):
                    existing = {}
                existing["upload_progress"] = info
                conn.execute(
                    text(
                        "UPDATE publish_plans "
                        "SET meta_json = CAST(:m AS JSON), updated_at = NOW() "
                        "WHERE id = :id"
                    ),
                    {
                        "id": plan_id,
                        "m": json.dumps(existing, ensure_ascii=False, default=str),
                    },
                )
        except Exception:  # pragma: no cover - 进度写库失败不阻断上传
            logger.exception(
                "upload progress write_back failed plan=%s", plan_id
            )

        try:
            from app.services.pipeline.events import publish_plan_event

            publish_plan_event(plan_id, "upload_progress", {"plan_id": plan_id, **info})
        except Exception:  # pragma: no cover - SSE 推送失败也只记日志
            logger.exception(
                "upload progress SSE publish failed plan=%s", plan_id
            )

    return _cb


def _load_plan(plan_id: str) -> Optional[dict[str, Any]]:
    """读 plan + 关联 render 的扁平视图（render_url / aspect / duration 一起出来）。"""
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT p.id, p.file_id, p.run_id, p.render_id, p.platform, p.status,
                       p.scheduled_at, p.title, p.description, p.tags_json,
                       p.cover_url, p.meta_json, p.error, p.confirm_real_publish,
                       f.user_id,
                       r.url, r.aspect_ratio, r.duration_s
                  FROM publish_plans p
                  JOIN files f ON f.id = p.file_id
             LEFT JOIN renders r ON r.id = p.render_id
                 WHERE p.id = :id
                """
            ),
            {"id": plan_id},
        ).fetchone()
    if not row:
        return None
    tags = row[9] if isinstance(row[9], list) else []
    meta = row[11] if isinstance(row[11], dict) else {}
    return {
        "id": row[0],
        "file_id": row[1],
        "run_id": row[2],
        "render_id": row[3],
        "platform": row[4],
        "status": row[5],
        "scheduled_at": row[6],
        "title": row[7],
        "description": row[8],
        "tags": tags,
        "cover_url": row[10],
        "meta": meta,
        "error": row[12],
        "confirm_real_publish": bool(row[13]),
        "user_id": row[14],
        "render_url": row[15],
        "render_aspect_ratio": row[16],
        "render_duration_s": float(row[17]) if row[17] is not None else None,
    }


__all__ = [
    "execute_publish_plan",
    "list_supported_platforms",
    "PublishError",
    "PublishOutcome",
]
