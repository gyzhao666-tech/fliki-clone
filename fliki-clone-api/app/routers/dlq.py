"""死信队列查询 / 重投 / 丢弃 API。

所有端点都按 `dead_letter_tasks.user_id = current_user.id` 过滤；
DLQ 项是从 `pipeline_runs.user_id` 反推填的，所以 user 只能看 / 操作自己的死信。

重投策略：
- 不在 service 层硬编码调度——根据 `task_name` 在路由层显式分发：
  - `publish.execute_plan` → `execute_publish_plan_task` / `_publish_execute_with_events`
    （Track-15：publish 死信原本被错误路由到 tick_task，根本不会真重发布；
    这条独立 task 没有 run_id，args 是 `[plan_id]` + kwargs `{"user_id": ...}`，
    必须直接派 publish task）
  - `pipeline.tick` / `pipeline.execute_step` / `background.tick` →
    `tick_task.delay(run_id)`（tick 会重新 claim ready step，等价于 _schedule_tick）
- 重投后 DLQ 项标 `retried`；如果再次失败会**新增一行**（不复用旧行）便于审计
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.deps import CurrentUser
from app.services.pipeline import dlq as pipeline_dlq

# 注意：从 pipelines 路由复用 _schedule_tick 会引入循环 import，
# 这里直接 import dispatcher 函数（与 pipelines.py 等价实现）
from app.config import get_settings


router = APIRouter(prefix="/dlq", tags=["DLQ"])


class DLQItemOut(BaseModel):
    id: str
    task_name: str
    args_json: Optional[list[Any]] = None
    kwargs_json: Optional[dict[str, Any]] = None
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    user_id: Optional[str] = None
    error: str
    traceback: Optional[str] = None
    attempt_count: int
    status: str
    notes: Optional[str] = None
    first_failed_at: datetime
    last_failed_at: datetime
    created_at: datetime
    updated_at: datetime


class RetryResult(BaseModel):
    id: str
    dispatcher: str = Field(..., description="celery / background")
    notes: Optional[str] = None


class DiscardBody(BaseModel):
    notes: Optional[str] = None


def _to_out(d: dict[str, Any]) -> DLQItemOut:
    return DLQItemOut(**d)


@router.get("", response_model=list[DLQItemOut])
async def list_dlq(
    current_user: CurrentUser,
    status: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,
) -> list[DLQItemOut]:
    items = pipeline_dlq.list_for_user(
        current_user.id, status=status, run_id=run_id, limit=min(limit, 500)
    )
    return [_to_out(i) for i in items]


@router.get("/{dlq_id}", response_model=DLQItemOut)
async def get_dlq(dlq_id: str, current_user: CurrentUser) -> DLQItemOut:
    item = pipeline_dlq.get(dlq_id)
    if not item:
        raise HTTPException(status_code=404, detail="dlq item not found")
    if item.get("user_id") and item["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="not your dlq item")
    return _to_out(item)


@router.post("/{dlq_id}/retry", response_model=RetryResult)
async def retry_dlq(
    dlq_id: str,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> RetryResult:
    item = pipeline_dlq.get(dlq_id)
    if not item:
        raise HTTPException(status_code=404, detail="dlq item not found")
    if item.get("user_id") and item["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="not your dlq item")
    if item["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"only pending items can be retried (current: {item['status']})",
        )

    dispatcher = _retry_dispatch(item, background_tasks)
    pipeline_dlq.mark(dlq_id, new_status="retried", notes=f"retried via {dispatcher}")
    return RetryResult(
        id=dlq_id,
        dispatcher=dispatcher,
        notes=f"re-queued ({item.get('task_name') or 'unknown'})",
    )


@router.post("/{dlq_id}/discard", response_model=DLQItemOut)
async def discard_dlq(
    dlq_id: str,
    current_user: CurrentUser,
    body: Optional[DiscardBody] = None,
) -> DLQItemOut:
    item = pipeline_dlq.get(dlq_id)
    if not item:
        raise HTTPException(status_code=404, detail="dlq item not found")
    if item.get("user_id") and item["user_id"] != current_user.id:
        raise HTTPException(status_code=403, detail="not your dlq item")
    if item["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"only pending items can be discarded (current: {item['status']})",
        )
    notes = (body.notes if body else None) or "discarded by user"
    pipeline_dlq.mark(dlq_id, new_status="discarded", notes=notes)
    refreshed = pipeline_dlq.get(dlq_id)
    assert refreshed is not None
    return _to_out(refreshed)


def _retry_dispatch(dead: dict[str, Any], background_tasks: BackgroundTasks) -> str:
    """根据 ``dead.task_name`` 派发到正确的 task；返回 dispatcher 名（celery / background）。

    Track-15 修复：原版只识别 tick 路径，把 publish.execute_plan 死信也丢进 tick_task
    → worker 收到的是 tick payload，而 plan_id 在 args[0]、根本不是 run_id，
    实际行为是「tick 一个不存在的 run id」直接 settle，发布从未真重投。

    分发矩阵（与 ``_publish_execute_with_events`` / ``execute_publish_plan_task`` 对齐）：

    - ``publish.execute_plan``：``args=[plan_id]`` + ``kwargs.user_id``；直接派 publish task
    - 其余（``pipeline.tick`` / ``pipeline.execute_step`` / ``background.tick``）：
      由 tick_task 自然 re-claim 死掉的 step，等价于 ``_schedule_tick``
    """

    task_name = (dead.get("task_name") or "").strip()
    settings = get_settings()

    # ── publish.execute_plan：路由到正确的 publish task ────────────────────────
    if task_name == "publish.execute_plan":
        args = list(dead.get("args_json") or [])
        kwargs = dict(dead.get("kwargs_json") or {})
        plan_id = (args[0] if args else None) or kwargs.get("plan_id")
        # user_id 优先 kwargs（push 时显式带），fallback 到 dlq 行级 user_id
        user_id = kwargs.get("user_id") or dead.get("user_id")
        if not plan_id:
            raise HTTPException(
                status_code=400,
                detail="publish.execute_plan dlq item missing plan_id; cannot retry",
            )

        if settings.celery_enabled:
            # 局部 import：避免在 web 进程启动时把 celery_app 牵进 router
            from app.services.pipeline.tasks import execute_publish_plan_task

            execute_publish_plan_task.apply_async(
                args=[plan_id],
                kwargs={"user_id": user_id},
                queue="default",
            )
            return "celery"

        # BackgroundTasks fallback：用与 celery task 同体的共享函数，保 SSE 语义一致
        from app.services.pipeline.tasks import _publish_execute_with_events

        background_tasks.add_task(_publish_execute_with_events, plan_id, user_id)
        return "background"

    # ── 既有路径：tick_task / runner.tick（pipeline 调度类死信）──────────────
    run_id = dead.get("run_id")
    if not run_id:
        raise HTTPException(
            status_code=400,
            detail=(
                f"dlq item (task={task_name or 'unknown'}) has no run_id; "
                "cannot dispatch via tick"
            ),
        )

    if settings.celery_enabled:
        from app.services.pipeline.tasks import tick_task

        tick_task.delay(run_id)
        return "celery"
    from app.services.pipeline.runner import tick

    background_tasks.add_task(tick, run_id)
    return "background"


__all__ = ["router"]
