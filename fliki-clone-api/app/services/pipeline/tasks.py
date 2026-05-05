"""Celery 任务：把 Pipeline 调度 + Publish 执行从 BackgroundTasks 解放到 worker pool。

Pipeline 调度（沿用）
--------------------
- `pipeline.tick`         : 调度一轮——claim 一个 ready step 派发到对应队列；没 ready 时 settle run state
- `pipeline.execute_step` : 在 worker 里执行单 step；完成后链式 `tick.delay(run_id)` 触发下一轮

Publish 执行（Track-03 新增）
----------------------------
- `publish.execute_plan`  : 把 `/publish-plans/{id}/execute` 30-60s 的 youtube upload
  从 HTTP 请求生命周期里搬到 worker；进入/完成时通过 `events.publish_plan_event`
  推 SSE 让前端 PlanRow 实时更新 status。task 体走 `_publish_execute_with_events`
  共享函数；BackgroundTasks fallback 模式（`CELERY_ENABLED=false`）由 router 直接
  把同一函数喂给 `BackgroundTasks.add_task`，保证两条路径 SSE 语义完全一致。

为什么不让 tick 一次性派发所有 ready step？
- v1 runner 默认顺序执行，重跑/审批语义清晰
- 同 run 内 ready 阶段一般也只有 1-2 个并发分支（research-script 串、video-art-voice 偶有并行）
- 一步一派发让 settle 时机可预测；多 step 并行可由 graph 自行设计依赖来表达

幂等性：
- `_claim_next_ready_step` 是「找一个 pending 且依赖全 succeeded 的 step」的纯查询，多次 tick
  不会重复派发同一 step（除非 step 被 rerun）
- `execute_step` 内部会标 step 为 running，再次进入 tick 时 state ≠ pending 自然跳过
- Publish 执行：executor 内部已经按 `plan.status='published'` 拒绝重发，task 重投也安全

死信队列（DLQ）：
- 业务异常已被 `execute_step()` 翻译成 `StepResult.FAILED`，不会进 DLQ（属于正常状态机）
- worker SIGKILL / OOM / 序列化错 / DB 连接异常等抛到 task 层 → 在 `DLQAwareTask.on_failure`
  里入 `dead_letter_tasks` 表
- `tick_task` 仍保留 3 次重试 + 指数退避；`execute_step_task` 不重试（媒体生成成本太高，让 user 决定重投）
- 重试耗尽后 celery 自动调 `on_failure` 入库；user 可在 `/api/dlq/...` 端点列表 + 重投 + 丢弃
- Publish 任务**不**用 DLQAwareTask：DLQ 入库由 `_publish_execute_with_events` 内部
  显式 push（带 `user_id` + plan args，方便前端 DLQ panel 与凭证误绑场景关联）
"""
from __future__ import annotations

import logging
import traceback as _tb
from typing import Any

import celery

from . import dlq as pipeline_dlq
from . import events as pipeline_events
from .celery_app import celery_app, queue_for_agent
from .runner import (
    _claim_next_ready_step,
    _settle_run_state,
    execute_step,
)
from .types import StepStatus

logger = logging.getLogger(__name__)


class DLQAwareTask(celery.Task):
    """所有 retry 耗尽后入 dead_letter_tasks 表的 base task。

    Celery 保证 `on_failure` 只在最后一次失败（max_retries 用尽）后调用，
    所以这里入 DLQ 是「确实救不回来了」的语义。
    """

    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        """重试耗尽后入 DLQ。einfo 含完整 traceback。"""

        try:
            run_id = _maybe_arg(args, kwargs, "run_id", index=0)
            step_id = None
            # execute_step_task(step_id, run_id) → args[0] 是 step_id
            if self.name == "pipeline.execute_step":
                step_id = _maybe_arg(args, kwargs, "step_id", index=0)
                run_id = _maybe_arg(args, kwargs, "run_id", index=1)

            traceback_str = (
                str(einfo.traceback) if einfo and getattr(einfo, "traceback", None) else None
            )
            pipeline_dlq.push(
                task_name=self.name,
                args=list(args) if args else [],
                kwargs=dict(kwargs) if kwargs else {},
                error=f"{type(exc).__name__}: {exc}",
                traceback_str=traceback_str,
                run_id=run_id,
                step_id=step_id,
            )
        except Exception:  # pragma: no cover
            logger.exception("DLQ on_failure hook itself raised")

        return super().on_failure(exc, task_id, args, kwargs, einfo)


def _maybe_arg(
    args: tuple, kwargs: dict, name: str, *, index: int
) -> Any:
    if kwargs and name in kwargs:
        return kwargs[name]
    if args and len(args) > index:
        return args[index]
    return None


@celery_app.task(
    name="pipeline.tick",
    base=DLQAwareTask,
    bind=True,
    queue="default",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
def tick_task(self, run_id: str) -> dict[str, Any]:  # noqa: D401
    """调度一步；不阻塞 step 执行，立即返回。"""

    next_step = _claim_next_ready_step(run_id)
    if next_step is None:
        new_state = _settle_run_state(run_id)
        logger.info("tick: run %s no ready step; settled to %s", run_id, new_state)
        return {"action": "settle", "run_id": run_id, "state": new_state}

    queue = queue_for_agent(next_step["agent_type"])
    execute_step_task.apply_async(
        args=[next_step["id"], run_id],
        queue=queue,
    )
    logger.info(
        "tick: run %s dispatched step %s (agent=%s) → queue=%s",
        run_id,
        next_step["name"],
        next_step["agent_type"],
        queue,
    )
    return {
        "action": "dispatched",
        "run_id": run_id,
        "step_id": next_step["id"],
        "step_name": next_step["name"],
        "agent_type": next_step["agent_type"],
        "queue": queue,
    }


@celery_app.task(
    name="pipeline.execute_step",
    base=DLQAwareTask,
    bind=True,
    queue="default",
    autoretry_for=(),  # 单步内部已经把异常翻译成 StepResult.FAILED；不在 task 层重试
    max_retries=0,
    acks_late=True,
)
def execute_step_task(self, step_id: str, run_id: str) -> dict[str, Any]:  # noqa: D401
    """在 worker 里跑一个 step；完成后链式触发下一轮 tick。

    `execute_step` 内部已经把业务异常翻译成 StepResult.FAILED；
    抛到这里的是真正不可恢复的异常（OOM / 序列化错 / worker_lost 重发耗尽），
    会被 DLQAwareTask.on_failure 拦截入 DLQ。
    """

    result = execute_step(step_id)
    # 不论成功 / 失败 / 等待审批，都让 tick 继续推进；
    # awaiting_review 时 tick 进 settle 分支，run 状态会变成 awaiting_review，
    # user 审批通过后再外部触发一次 tick.delay 即可继续。
    tick_task.apply_async(args=[run_id], queue="default")
    return {
        "step_id": step_id,
        "run_id": run_id,
        "status": result.status.value
        if isinstance(result.status, StepStatus)
        else str(result.status),
        "cost_usd": float(result.cost_usd or 0.0),
        "error": result.error,
    }


# ── Track-03：publish 任务异步化 ───────────────────────────────────────────────
# 设计要点：
# 1. task 体抽到 `_publish_execute_with_events`，让 celery worker 与 BackgroundTasks
#    fallback 共用同一份 SSE 广播 + DLQ 写入逻辑
# 2. 不挂 DLQAwareTask base：DLQ 入库由函数体显式 push（带 user_id + plan_id args
#    方便 DLQ panel 关联凭证误绑等场景）；task 层 max_retries=0，避免重试期间用户
#    多次点 Upload 导致同 plan 多次执行
# 3. SSE 三个 phase：
#       running         ── task 拿到执行权，executor 即将调 adapter
#       completed       ── adapter 返回（不论 ok/failed 业务结果都算 completed）
#       system_error    ── PublishError / 不可恢复异常（已入 DLQ，前端弹错并提示去 DLQ）


def _publish_execute_with_events(plan_id: str, user_id: str) -> dict[str, Any]:
    """共享业务体；celery task 与 BackgroundTasks 都直接调它。

    返回值用于日志 / 测试断言，前端不消费（前端只看 SSE 推的事件）。
    任何异常都被吞掉并广播到 SSE，避免未捕获异常让 worker 进程退出。
    """

    # 局部 import：避免 worker 启动时把 publishing/executor 牵进 router 路径
    # （executor 又要 import publishing.adapters 触发自注册，与 web 进程共用 OK）
    from app.services.publishing import PublishError, execute_publish_plan

    pipeline_events.publish_plan_event(
        plan_id,
        "publish_plan_state",
        {"plan_id": plan_id, "phase": "running"},
    )

    try:
        outcome = execute_publish_plan(plan_id, user_id=user_id)
    except PublishError as exc:
        # 系统级异常：进 DLQ，让用户在 DLQ panel 重投；广播 system_error 让前端摘 loading
        try:
            pipeline_dlq.push(
                task_name="publish.execute_plan",
                args=[plan_id],
                kwargs={"user_id": user_id},
                user_id=user_id,
                error=str(exc),
            )
        except Exception:  # pragma: no cover - DLQ 写失败不阻断 SSE
            logger.exception("DLQ push failed for publish plan %s", plan_id)
        pipeline_events.publish_plan_event(
            plan_id,
            "publish_plan_state",
            {
                "plan_id": plan_id,
                "phase": "system_error",
                "ok": False,
                "status": "failed",
                "error": str(exc),
            },
        )
        return {
            "plan_id": plan_id,
            "ok": False,
            "phase": "system_error",
            "error": str(exc),
        }
    except Exception as exc:  # pragma: no cover - 防御
        # 不在 PublishError 白名单里的（连接错 / OOM / 序列化错 / adapter 内未捕获）
        try:
            pipeline_dlq.push(
                task_name="publish.execute_plan",
                args=[plan_id],
                kwargs={"user_id": user_id},
                user_id=user_id,
                error=f"{type(exc).__name__}: {exc}",
                traceback_str=_tb.format_exc(),
            )
        except Exception:
            logger.exception("DLQ push failed for publish plan %s", plan_id)
        pipeline_events.publish_plan_event(
            plan_id,
            "publish_plan_state",
            {
                "plan_id": plan_id,
                "phase": "system_error",
                "ok": False,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return {
            "plan_id": plan_id,
            "ok": False,
            "phase": "system_error",
            "error": str(exc),
        }

    pipeline_events.publish_plan_event(
        plan_id,
        "publish_plan_state",
        {
            "plan_id": plan_id,
            "phase": "completed",
            "ok": outcome.ok,
            "status": "published" if outcome.ok else "failed",
            "external_id": outcome.external_id,
            "external_url": outcome.external_url,
            "error": outcome.error,
        },
    )
    return {
        "plan_id": plan_id,
        "ok": outcome.ok,
        "phase": "completed",
        "status": "published" if outcome.ok else "failed",
        "external_id": outcome.external_id,
    }


@celery_app.task(
    name="publish.execute_plan",
    bind=True,
    queue="default",
    autoretry_for=(),  # 不在 task 层重试；失败靠 DLQ + 用户决定 retry
    max_retries=0,
    acks_late=True,
)
def execute_publish_plan_task(
    self, plan_id: str, user_id: str
) -> dict[str, Any]:  # noqa: D401
    """Celery 入口；body 全部委托给 `_publish_execute_with_events`。"""

    return _publish_execute_with_events(plan_id, user_id)


# 兼容旧 import：从 pipeline.tasks 直接拿 tick_task / execute_step_task
__all__ = [
    "celery_app",
    "tick_task",
    "execute_step_task",
    "DLQAwareTask",
    # Track-03
    "execute_publish_plan_task",
    "_publish_execute_with_events",
]
