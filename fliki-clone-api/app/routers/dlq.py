"""死信队列查询 / 重投 / 丢弃 API。

所有端点都按 `dead_letter_tasks.user_id = current_user.id` 过滤；
DLQ 项是从 `pipeline_runs.user_id` 反推填的，所以 user 只能看 / 操作自己的死信。

重投策略：
- 不在 service 层硬编码调度——根据 `task_name` 在路由层显式分发：
  - `pipeline.tick` / `background.tick` → `_schedule_tick(run_id, ...)`（沿用 pipelines.py 路径）
  - `pipeline.execute_step` → 直接 `tick_task.delay(run_id)`（同效果：tick 会重新 claim 那个 step）
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

    run_id = item.get("run_id")
    if not run_id:
        raise HTTPException(
            status_code=400,
            detail="dlq item has no run_id; cannot dispatch via tick",
        )

    dispatcher = _retry_dispatch(run_id, background_tasks)
    pipeline_dlq.mark(dlq_id, new_status="retried", notes=f"retried via {dispatcher}")
    return RetryResult(id=dlq_id, dispatcher=dispatcher, notes="re-queued via tick")


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


def _retry_dispatch(run_id: str, background_tasks: BackgroundTasks) -> str:
    """与 pipelines.py::_schedule_tick 等效；不直接 import 避免循环依赖。"""

    if get_settings().celery_enabled:
        from app.services.pipeline.tasks import tick_task

        tick_task.delay(run_id)
        return "celery"
    from app.services.pipeline.runner import tick

    background_tasks.add_task(tick, run_id)
    return "background"


__all__ = ["router"]
