"""死信队列 service：异常入库 + 列表 + 重投 + 丢弃。

调用方：
- celery `Task.on_failure` hook（worker 异常 / acks_late 重发耗尽）
- runner BackgroundTasks 模式的 `_handle_dispatch_failure`（同进程异常）
- API 路由 `routers/dlq.py`

幂等：
- `push` 用 `(task_name, args)` 做软去重（同一 logical task 反复失败 → 同一行 attempt_count++
  + last_failed_at 更新，不重复建行）
- `retry` 把 status 标 `retried`，但**不**自动重投——返回反序列化好的 task 名 + args
  让上层（router）走 `_schedule_tick`/`celery_app` 重投，避免在 service 层硬编码调度
"""
from __future__ import annotations

import json
import logging
import traceback as _tb
import uuid
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger(__name__)


def _engine():
    return create_engine(get_settings().database_url_sync)


def _serialise_args(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _user_id_for_run(conn, run_id: Optional[str]) -> Optional[str]:
    if not run_id:
        return None
    row = conn.execute(
        text("SELECT user_id FROM pipeline_runs WHERE id = :rid"), {"rid": run_id}
    ).fetchone()
    return row[0] if row else None


def push(
    *,
    task_name: str,
    args: Optional[list[Any]] = None,
    kwargs: Optional[dict[str, Any]] = None,
    error: str,
    traceback_str: Optional[str] = None,
    run_id: Optional[str] = None,
    step_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """把一个死信记录写到 dead_letter_tasks；任何异常仅 warning，不阻断主流程。

    返回新行 id；同一 logical task 已存在 pending 行时返回该行 id（attempt_count++）。

    user_id 优先级：caller 显式传 > 从 run_id 推导 > None（无主任务，比如发布执行器）。
    """

    args_payload = list(args) if args else []
    args_json = _serialise_args(args_payload)
    kwargs_json = _serialise_args(kwargs or {})

    try:
        with _engine().begin() as conn:
            if user_id is None:
                user_id = _user_id_for_run(conn, run_id)

            # 软去重：同 (task_name, args, status='pending') → 累加 attempt
            existing = conn.execute(
                text(
                    "SELECT id, attempt_count FROM dead_letter_tasks "
                    "WHERE task_name = :tn AND status = 'pending' "
                    "  AND args_json::text = :args_text "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"tn": task_name, "args_text": args_json or "null"},
            ).fetchone()

            if existing:
                conn.execute(
                    text(
                        "UPDATE dead_letter_tasks "
                        "SET attempt_count = attempt_count + 1, "
                        "    last_failed_at = NOW(), updated_at = NOW(), "
                        "    error = :err, traceback = :tb "
                        "WHERE id = :id"
                    ),
                    {
                        "id": existing[0],
                        "err": (error or "")[:8000],
                        "tb": (traceback_str or "")[:32000] or None,
                    },
                )
                logger.warning(
                    "DLQ: bumped attempt for task=%s id=%s attempt=%s",
                    task_name, existing[0], int(existing[1] or 0) + 1,
                )
                return existing[0]

            new_id = str(uuid.uuid4())
            conn.execute(
                text(
                    "INSERT INTO dead_letter_tasks "
                    "(id, task_name, args_json, kwargs_json, run_id, step_id, user_id, "
                    " error, traceback, attempt_count, status) VALUES "
                    "(:id, :tn, CAST(:args AS JSON), CAST(:kw AS JSON), :rid, :sid, :uid, "
                    " :err, :tb, 1, 'pending')"
                ),
                {
                    "id": new_id,
                    "tn": task_name,
                    "args": args_json,
                    "kw": kwargs_json,
                    "rid": run_id,
                    "sid": step_id,
                    "uid": user_id,
                    "err": (error or "")[:8000],
                    "tb": (traceback_str or "")[:32000] or None,
                },
            )
            logger.warning(
                "DLQ: pushed task=%s id=%s run=%s step=%s err=%.200s",
                task_name, new_id, run_id, step_id, error,
            )
            return new_id
    except Exception:  # pragma: no cover - DLQ 写入失败不阻断主流程
        logger.exception("DLQ push failed: task=%s", task_name)
        return None


def push_from_exception(
    *,
    task_name: str,
    args: Optional[list[Any]] = None,
    kwargs: Optional[dict[str, Any]] = None,
    exc: BaseException,
    run_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> Optional[str]:
    """从 Exception 派生入库（自动 traceback）。"""

    return push(
        task_name=task_name,
        args=args,
        kwargs=kwargs,
        error=f"{type(exc).__name__}: {exc}",
        traceback_str=_tb.format_exc(),
        run_id=run_id,
        step_id=step_id,
    )


def mark(
    dlq_id: str,
    *,
    new_status: str,
    notes: Optional[str] = None,
) -> bool:
    """把 DLQ 项标为 retried / discarded。"""

    if new_status not in ("retried", "discarded", "pending"):
        return False
    try:
        with _engine().begin() as conn:
            res = conn.execute(
                text(
                    "UPDATE dead_letter_tasks "
                    "SET status = :st, notes = COALESCE(:notes, notes), updated_at = NOW() "
                    "WHERE id = :id"
                ),
                {"st": new_status, "notes": notes, "id": dlq_id},
            )
            return (res.rowcount or 0) > 0
    except Exception:  # pragma: no cover
        logger.exception("DLQ mark failed id=%s status=%s", dlq_id, new_status)
        return False


def get(dlq_id: str) -> Optional[dict[str, Any]]:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, task_name, args_json, kwargs_json, run_id, step_id, user_id, "
                "error, traceback, attempt_count, status, notes, "
                "first_failed_at, last_failed_at, created_at, updated_at "
                "FROM dead_letter_tasks WHERE id = :id"
            ),
            {"id": dlq_id},
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_for_user(
    user_id: str,
    *,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    where = ["user_id = :uid"]
    params: dict[str, Any] = {"uid": user_id, "lim": limit}
    if status:
        where.append("status = :st")
        params["st"] = status
    if run_id:
        where.append("run_id = :rid")
        params["rid"] = run_id

    sql = (
        "SELECT id, task_name, args_json, kwargs_json, run_id, step_id, user_id, "
        "error, traceback, attempt_count, status, notes, "
        "first_failed_at, last_failed_at, created_at, updated_at "
        "FROM dead_letter_tasks WHERE " + " AND ".join(where) +
        " ORDER BY created_at DESC LIMIT :lim"
    )
    with _engine().connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "task_name": row[1],
        "args_json": row[2],
        "kwargs_json": row[3],
        "run_id": row[4],
        "step_id": row[5],
        "user_id": row[6],
        "error": row[7],
        "traceback": row[8],
        "attempt_count": int(row[9] or 0),
        "status": row[10],
        "notes": row[11],
        "first_failed_at": row[12],
        "last_failed_at": row[13],
        "created_at": row[14],
        "updated_at": row[15],
    }


__all__ = ["push", "push_from_exception", "mark", "get", "list_for_user"]
