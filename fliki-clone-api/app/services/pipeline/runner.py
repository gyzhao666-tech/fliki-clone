"""Pipeline 执行器（v1：同进程顺序版）。

v1 目标只为打通端到端：
- `start_run(...)` 创建 PipelineRun + 所有 PipelineStep
- `tick(run_id)` 推进一次（执行所有 ready step）
- `execute_step(step_id)` 执行单个 step（被 Celery / BackgroundTask 调用）

Phase 2 替换为 Celery 队列分级 + 调度器，不影响 Step 协议与外部接口。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import create_engine, text

from app.config import get_settings
from app.models.pipeline import PipelineRun, PipelineStep  # noqa: F401  保证模型注册

from . import dlq as pipeline_dlq
from . import events as pipeline_events
from . import persist as pipeline_persist
from .types import (
    PipelineContext,
    StepResult,
    StepStatus,
    get_agent_class,
)

logger = logging.getLogger(__name__)


def _engine():
    return create_engine(get_settings().database_url_sync)


# ── 创建 ──────────────────────────────────────────────────────────────────────


def start_run(
    *,
    user_id: Optional[str],
    file_id: Optional[str],
    template_name: str,
    graph: list[dict[str, Any]],
    inputs: Optional[dict[str, Any]] = None,
    cost_estimated_usd: float = 0.0,
    cost_reserved_usd: float = 0.0,
    tenant_id: Optional[str] = None,
) -> str:
    """创建一个 PipelineRun 与全部 step。

    `graph` 形如：
        [
            {"name": "research", "agent_type": "research", "depends_on": []},
            {"name": "script",   "agent_type": "script",   "depends_on": ["research"]},
        ]

    `cost_estimated_usd` / `cost_reserved_usd`：调用方在配额预扣完成后传入，便于审计与
    终态退还。
    `tenant_id`（配额 v2）：tenant 命名空间，用于终态退还路径。不传则从 user_id 推断
    （`u:{user_id}`）兜底。

    返回 run_id。
    """
    run_id = str(uuid.uuid4())
    inputs = inputs or {}
    if not tenant_id and user_id:
        tenant_id = f"u:{user_id}"

    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO pipeline_runs
                    (id, file_id, user_id, tenant_id, template_name, state,
                     graph_json, inputs_json,
                     cost_estimated_usd, cost_actual_usd, cost_reserved_usd,
                     created_at, updated_at)
                VALUES
                    (:id, :file_id, :user_id, :tenant_id, :tmpl, 'queued',
                     CAST(:graph AS JSON), CAST(:inputs AS JSON),
                     :est, 0, :reserved, NOW(), NOW())
                """
            ),
            {
                "id": run_id,
                "file_id": file_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "tmpl": template_name,
                "graph": _json(graph),
                "inputs": _json(inputs),
                "est": float(cost_estimated_usd or 0.0),
                "reserved": float(cost_reserved_usd or 0.0),
            },
        )

        for node in graph:
            conn.execute(
                text(
                    """
                    INSERT INTO pipeline_steps
                        (id, run_id, name, agent_type, depends_on_json, state, attempt,
                         requires_review, created_at)
                    VALUES
                        (:id, :run_id, :name, :agent_type, CAST(:deps AS JSON), 'pending',
                         0, :requires_review, NOW())
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "name": node["name"],
                    "agent_type": node["agent_type"],
                    "deps": _json(node.get("depends_on") or []),
                    "requires_review": 1 if node.get("requires_review") else 0,
                },
            )

    return run_id


# ── 调度 ──────────────────────────────────────────────────────────────────────


def tick(run_id: str) -> dict[str, Any]:
    """推进一次：把依赖完成的 step 标为 ready 并依次执行。

    v1 是同进程顺序执行；返回执行了哪些 step 与最终 run state。
    BackgroundTasks 模式下任何未捕获异常会进 DLQ（celery 模式下走 DLQAwareTask.on_failure）。
    """
    try:
        return _tick_inner(run_id)
    except Exception as exc:  # 兜底：BackgroundTasks 模式下没有 task 层 retry
        pipeline_dlq.push_from_exception(
            task_name="background.tick",
            args=[run_id],
            exc=exc,
            run_id=run_id,
        )
        logger.exception("background tick failed run=%s", run_id)
        return {"error": str(exc), "executed": []}


def _tick_inner(run_id: str) -> dict[str, Any]:
    executed: list[str] = []
    with _engine().begin() as conn:
        run_row = conn.execute(
            text("SELECT id, state, file_id, user_id FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
        if not run_row:
            return {"error": "run not found", "executed": executed}
        if run_row[1] in ("succeeded", "failed", "cancelled"):
            return {"state": run_row[1], "executed": executed}

        # 标记 run 为 running
        conn.execute(
            text("UPDATE pipeline_runs SET state = 'running', updated_at = NOW() WHERE id = :id"),
            {"id": run_id},
        )

    # 立即广播 running（无论是 queued→running 还是 running→running 的「重新开跑」）
    _publish_run_state(run_id)

    while True:
        next_step = _claim_next_ready_step(run_id)
        if not next_step:
            break
        executed.append(next_step["name"])
        execute_step(next_step["id"])

    final_state = _settle_run_state(run_id)
    return {"state": final_state, "executed": executed}


def execute_step(step_id: str) -> StepResult:
    """执行单个 step；状态机由本函数维护，调用方不需要再 update。"""

    step_row = _load_step(step_id)
    if not step_row:
        return StepResult(status=StepStatus.FAILED, error="step not found")

    agent_cls = get_agent_class(step_row["agent_type"])
    if not agent_cls:
        _mark_step_failed(step_id, f"agent_type {step_row['agent_type']} not registered")
        return StepResult(
            status=StepStatus.FAILED,
            error=f"agent_type {step_row['agent_type']} not registered",
        )

    upstream_outputs = _load_upstream_outputs(step_row["run_id"], step_row.get("depends_on") or [])
    inputs = step_row.get("inputs") or _load_run_inputs(step_row["run_id"])
    run_user_id = _load_run_user(step_row["run_id"])
    run_tenant = _load_run_tenant(step_row["run_id"])
    ctx = PipelineContext(
        run_id=step_row["run_id"],
        step_id=step_id,
        user_id=run_user_id,
        file_id=_load_run_file(step_row["run_id"]),
        inputs=inputs,
        upstream_outputs=upstream_outputs,
        tenant_id=run_tenant.get("tenant_id"),
        tenant_plan=run_tenant.get("plan") or "free",
    )

    _mark_step_running(step_id)
    try:
        result = agent_cls().run(ctx)
    except Exception as exc:
        logger.exception("step %s raised", step_id)
        result = StepResult(status=StepStatus.FAILED, error=str(exc))

    if result.status == StepStatus.SUCCEEDED:
        _mark_step_succeeded(step_id, result)
    elif result.status == StepStatus.AWAITING_REVIEW:
        _mark_step_awaiting_review(step_id, result)
    elif result.status == StepStatus.SKIPPED:
        _mark_step_succeeded(step_id, result)
    else:
        _mark_step_failed(step_id, result.error or "unknown error", outputs=result.outputs)

    return result


def rerun_step(step_id: str) -> StepResult:
    """单步重跑：直接清状态后再执行。"""

    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_steps
                   SET state = 'pending', attempt = attempt + 1, error = NULL,
                       outputs_json = NULL, started_at = NULL, finished_at = NULL
                 WHERE id = :id
                """
            ),
            {"id": step_id},
        )
    return execute_step(step_id)


# ── 内部 ──────────────────────────────────────────────────────────────────────


def _claim_next_ready_step(run_id: str) -> Optional[dict[str, Any]]:
    """找一个所有 depends_on 都 succeeded 的 pending step，并返回其字段。"""

    with _engine().begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, name, agent_type, depends_on_json, inputs_json
                  FROM pipeline_steps
                 WHERE run_id = :run_id AND state = 'pending'
                 ORDER BY created_at ASC
                """
            ),
            {"run_id": run_id},
        ).fetchall()

        for row in rows:
            deps = row[3] or []
            if not deps:
                return _row_to_step(row)
            ok = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM pipeline_steps
                     WHERE run_id = :run_id
                       AND name = ANY(:deps)
                       AND state = 'succeeded'
                    """
                ),
                {"run_id": run_id, "deps": list(deps)},
            ).scalar()
            if ok == len(deps):
                return _row_to_step(row)
    return None


def _row_to_step(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "agent_type": row[2],
        "depends_on": row[3] or [],
        "inputs": row[4] or {},
        "run_id": _load_step_run_id(row[0]),
    }


def _load_step(step_id: str) -> Optional[dict[str, Any]]:
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, run_id, name, agent_type, depends_on_json, inputs_json
                  FROM pipeline_steps WHERE id = :id
                """
            ),
            {"id": step_id},
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "run_id": row[1],
            "name": row[2],
            "agent_type": row[3],
            "depends_on": row[4] or [],
            "inputs": row[5] or {},
        }


def _load_step_run_id(step_id: str) -> Optional[str]:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT run_id FROM pipeline_steps WHERE id = :id"),
            {"id": step_id},
        ).fetchone()
        return row[0] if row else None


def _load_run_inputs(run_id: str) -> dict[str, Any]:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT inputs_json FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
        return (row[0] if row and row[0] else {}) or {}


def _load_run_user(run_id: str) -> Optional[str]:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT user_id FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
        return row[0] if row else None


def _load_run_file(run_id: str) -> Optional[str]:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT file_id FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
        return row[0] if row else None


def _load_run_tenant(run_id: str) -> dict[str, Optional[str]]:
    """读 run.tenant_id + 该 run owner 的 plan（用于 provider bucket 派生）。

    plan 缺失（demo / 匿名）→ 'free'。tenant_id 缺失（极老 run）→ None；
    gateway 内部会按 user_id 兜底再 resolve 一次。
    """
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT pr.tenant_id, u.plan
                  FROM pipeline_runs pr
                  LEFT JOIN users u ON u.id = pr.user_id
                 WHERE pr.id = :id
                """
            ),
            {"id": run_id},
        ).fetchone()
    if not row:
        return {"tenant_id": None, "plan": "free"}
    return {"tenant_id": row[0], "plan": row[1] or "free"}


def _load_upstream_outputs(run_id: str, dep_names: list[str]) -> dict[str, dict[str, Any]]:
    if not dep_names:
        return {}
    with _engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT name, outputs_json FROM pipeline_steps
                 WHERE run_id = :run_id AND name = ANY(:names)
                """
            ),
            {"run_id": run_id, "names": list(dep_names)},
        ).fetchall()
    return {r[0]: (r[1] or {}) for r in rows}


def _mark_step_running(step_id: str) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text("UPDATE pipeline_steps SET state='running', started_at=NOW() WHERE id=:id"),
            {"id": step_id},
        )
    _publish_step_state(step_id)


def _mark_step_succeeded(step_id: str, result: StepResult) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_steps
                   SET state='succeeded', outputs_json=CAST(:outputs AS JSON),
                       cost_usd=:cost, finished_at=NOW(), error=NULL
                 WHERE id=:id
                """
            ),
            {
                "id": step_id,
                "outputs": _json(result.outputs or {}),
                "cost": float(result.cost_usd or 0.0),
            },
        )
    _persist_step_outputs(step_id, result)
    _publish_step_state(step_id)


def _mark_step_awaiting_review(step_id: str, result: StepResult) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_steps
                   SET state='awaiting_review', outputs_json=CAST(:outputs AS JSON),
                       cost_usd=:cost, finished_at=NOW()
                 WHERE id=:id
                """
            ),
            {
                "id": step_id,
                "outputs": _json(result.outputs or {}),
                "cost": float(result.cost_usd or 0.0),
            },
        )
    # awaiting_review 也算 step 主体执行完成（user 之后 approve 才进 succeeded）
    # outputs 已经全部产出，应当持久化到生产表，让前端能立即在审批前看到拆分后的数据
    _persist_step_outputs(step_id, result)
    _publish_step_state(step_id)


def _mark_step_failed(step_id: str, err: str, outputs: Optional[dict[str, Any]] = None) -> None:
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_steps
                   SET state='failed', error=:err, finished_at=NOW(),
                       outputs_json=CAST(:outputs AS JSON)
                 WHERE id=:id
                """
            ),
            {
                "id": step_id,
                "err": err[:2000] if err else None,
                "outputs": _json(outputs or {}),
            },
        )
    _publish_step_state(step_id)


_TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


def _settle_run_state(run_id: str) -> str:
    """根据 step 状态设置 run 终态；首次进入终态时累加 actual_cost 并退还预扣差额。

    `partial_failed` 在 v1 不视为终态：人可以单步重跑修复。
    """

    with _engine().begin() as conn:
        run_row = conn.execute(
            text(
                """
                SELECT state, user_id, tenant_id, cost_reserved_usd
                  FROM pipeline_runs WHERE id = :id
                """
            ),
            {"id": run_id},
        ).fetchone()
        if not run_row:
            return "queued"
        prev_state = run_row[0]
        user_id = run_row[1]
        tenant_id = run_row[2]
        reserved = float(run_row[3] or 0.0)

        states = [
            row[0]
            for row in conn.execute(
                text("SELECT state FROM pipeline_steps WHERE run_id = :id"),
                {"id": run_id},
            ).fetchall()
        ]

        if not states:
            return prev_state or "queued"
        if any(s == "failed" for s in states):
            new_state = "partial_failed"
        elif any(s == "awaiting_review" for s in states):
            new_state = "awaiting_review"
        elif all(s in ("succeeded", "skipped") for s in states):
            new_state = "succeeded"
        else:
            new_state = "running"

        actual_cost: Optional[float] = None
        is_first_terminal = (
            prev_state not in _TERMINAL_STATES and new_state in _TERMINAL_STATES
        )
        if is_first_terminal:
            cost_row = conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM pipeline_steps WHERE run_id = :id"
                ),
                {"id": run_id},
            ).fetchone()
            actual_cost = float(cost_row[0] or 0.0) if cost_row else 0.0

        if actual_cost is not None:
            conn.execute(
                text(
                    """
                    UPDATE pipeline_runs
                       SET state=:s, updated_at=NOW(),
                           cost_actual_usd=:actual,
                           finished_at=NOW()
                     WHERE id=:id
                    """
                ),
                {"id": run_id, "s": new_state, "actual": actual_cost},
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE pipeline_runs
                       SET state=:s, updated_at=NOW()
                     WHERE id=:id
                    """
                ),
                {"id": run_id, "s": new_state},
            )

    if is_first_terminal:
        refund = reserved - (actual_cost or 0.0)
        if refund > 1e-6:
            # v2：tenant_id 优先；旧 run 缺 tenant_id 时从 user_id 推断
            effective_tid: Optional[str] = tenant_id
            if not effective_tid and user_id:
                effective_tid = f"u:{user_id}"
            if effective_tid:
                try:
                    from .quota import release_tenant  # 局部 import 避免循环

                    release_tenant(effective_tid, refund)
                except Exception:  # pragma: no cover - 退还失败不阻断
                    logger.exception(
                        "release tenant quota failed tenant=%s refund=%s",
                        effective_tid,
                        refund,
                    )

    # 仅在 state 真的变化时才广播，避免「running→running」噪声
    if new_state != prev_state:
        _publish_run_state(run_id)

    return new_state


# ── 持久化 hook（生产元数据表）─────────────────────────────────────────────


def _persist_step_outputs(step_id: str, result: StepResult) -> None:
    """读 step 的 run_id / agent_type，把 result.outputs 路由到对应生产表。"""

    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT run_id, agent_type FROM pipeline_steps WHERE id = :id"
                ),
                {"id": step_id},
            ).fetchone()
        if not row:
            return
        run_id, agent_type = row[0], row[1]
        pipeline_persist.persist_step_outputs(
            run_id=run_id,
            step_id=step_id,
            agent_type=agent_type,
            outputs=result.outputs,
        )
    except Exception:  # pragma: no cover - 持久化失败不阻断 step
        logger.exception("persist hook failed step_id=%s", step_id)


# ── 事件广播 ────────────────────────────────────────────────────────────────
# 每个 _mark_step_* 之后会 publish 一个 step_state 事件；_settle_run_state /
# tick / 路由 cancel/approve 之后会 publish run_state；前端拿到 envelope
# 直接 patch 本地状态，不再需要 polling。


def _publish_step_state(step_id: str) -> None:
    """从 DB 读完整字段并 publish；任何失败只 warn，不阻断主流程。"""

    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, run_id, name, agent_type, state, attempt,
                           requires_review, inputs_json, outputs_json, error, cost_usd
                      FROM pipeline_steps WHERE id = :id
                    """
                ),
                {"id": step_id},
            ).fetchone()
        if not row:
            return
        payload = {
            "id": row[0],
            "run_id": row[1],
            "name": row[2],
            "agent_type": row[3],
            "state": row[4],
            "attempt": int(row[5] or 0),
            "requires_review": bool(row[6]),
            "inputs_json": row[7],
            "outputs_json": row[8],
            "error": row[9],
            "cost_usd": float(row[10] or 0.0),
        }
        pipeline_events.publish(row[1], "step_state", payload)
    except Exception:  # pragma: no cover - 广播失败不阻断
        logger.exception("publish step_state failed step_id=%s", step_id)


def _publish_run_state(run_id: str) -> None:
    """读 run 当前字段并广播；前端用它更新顶部状态徽标 + 成本卡片。"""

    try:
        with _engine().connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id, file_id, user_id, template_name, state,
                           cost_estimated_usd, cost_actual_usd, cost_reserved_usd, error
                      FROM pipeline_runs WHERE id = :id
                    """
                ),
                {"id": run_id},
            ).fetchone()
        if not row:
            return
        payload = {
            "id": row[0],
            "file_id": row[1],
            "user_id": row[2],
            "template_name": row[3],
            "state": row[4],
            "cost_estimated_usd": float(row[5] or 0.0),
            "cost_actual_usd": float(row[6] or 0.0),
            "cost_reserved_usd": float(row[7] or 0.0),
            "error": row[8],
        }
        pipeline_events.publish(run_id, "run_state", payload)
    except Exception:  # pragma: no cover
        logger.exception("publish run_state failed run_id=%s", run_id)


def _json(value: Any) -> str:
    import json as _json_mod

    return _json_mod.dumps(value, ensure_ascii=False)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)
