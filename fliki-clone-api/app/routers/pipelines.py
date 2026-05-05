"""Pipeline 路由（最小可用版本）。

提供 ADR-001 中描述的核心接口：启动 / 查询 / 推进 / 单步重跑 / 审批，
以及 SSE 流式推送端点 `GET /pipelines/{run_id}/events`（替代前端 2.5s polling）。

设计取舍：
- v1 用同步 tick + BackgroundTasks 推进；不阻塞请求
- SSE 由 Redis pub/sub 驱动；连接时先发 snapshot 对齐，之后只发增量；终态后服务端关闭
- agents 在本模块顶部 import 一次以触发自注册
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.deps import CurrentUser
from app.services.auth.rbac import require_role
from app.services.pipeline import agents as _agents  # noqa: F401  触发 agent 自注册
from app.services.pipeline import events as pipeline_events
from app.services.pipeline import templates as pipeline_templates
from app.services.pipeline import provider_buckets as pipeline_buckets
from app.services.pipeline import tenant as pipeline_tenant
from app.services.pipeline.cost import estimate_pipeline_cost
from app.services.pipeline.quota import (
    TenantQuotaSnapshot,
    count_active_runs_tenant,
    get_or_create_tenant,
    release_tenant,
    reserve_tenant,
)
from app.services.pipeline.runner import (
    execute_step,
    rerun_step,
    start_run,
    tick,
)

logger = logging.getLogger(__name__)


# Track-27 · pipeline 写权限：admin / editor 都能启停 / 推进；viewer 只能读
_writer_required = Depends(require_role(["admin", "editor"]))


def _schedule_tick(run_id: str, background_tasks: BackgroundTasks) -> str:
    """抽象的「下一步推进」调度器。

    - `celery_enabled=True`：派发 `pipeline.tick` 到 default 队列；step 在 agent 对应队列异步执行
    - `celery_enabled=False`：保持 BackgroundTasks 同进程顺序（dev / 没起 redis 也能跑）

    返回 dispatcher 名，便于日志 / 测试。
    """
    if get_settings().celery_enabled:
        # 局部 import：未启 celery 时不加载 worker 依赖路径
        from app.services.pipeline.tasks import tick_task

        tick_task.delay(run_id)
        return "celery"
    background_tasks.add_task(tick, run_id)
    return "background"


router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class StartPipelineRequest(BaseModel):
    template_name: str = Field(..., description="内置模板名，例如 script_only")
    file_id: Optional[str] = Field(None, description="可选的 file 绑定；不传则当成独立 run")
    brief: dict[str, Any] = Field(default_factory=dict, description="完整 Brief")
    target_topic: Any = Field(None, description="可指定具体选题；不传则用 research 第一条")
    custom_graph: Optional[list[dict[str, Any]]] = Field(
        None, description="高级用法：直接传 DAG，覆盖 template_name"
    )


class StepOut(BaseModel):
    id: str
    name: str
    agent_type: str
    state: str
    attempt: int
    requires_review: bool
    inputs_json: Optional[dict[str, Any]] = None
    outputs_json: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    cost_usd: float = 0.0


class RunOut(BaseModel):
    id: str
    file_id: Optional[str] = None
    user_id: Optional[str] = None
    template_name: Optional[str] = None
    state: str
    cost_estimated_usd: float = 0.0
    cost_actual_usd: float = 0.0
    cost_reserved_usd: float = 0.0
    error: Optional[str] = None
    steps: list[StepOut] = []


class ProviderBucketOut(BaseModel):
    provider_name: str
    current_in_flight: int
    max_concurrent: int
    remaining: int
    utilization_pct: float


class QuotaOut(BaseModel):
    """配额 v2 响应：tenant 视图为权威源；保留 user 视图字段名兼容旧前端。

    旧前端字段名（`monthly_limit_usd` / `current_period_usage_usd` / ...）继续映射到
    tenant 数据，让历史 UI 不拆。
    """
    monthly_limit_usd: float
    current_period_usage_usd: float
    remaining_usd: float
    current_period_start: str
    concurrent_max: int
    active_runs: int
    # v2 新增：tenant 显式字段
    tenant_id: str
    tenant_plan: str
    tenant_display_name: Optional[str] = None
    provider_buckets: list[ProviderBucketOut] = []


class CostEstimateOut(BaseModel):
    total_usd: float
    by_step: list[dict[str, Any]]
    missing_agents: list[str] = []


# ── helpers ───────────────────────────────────────────────────────────────────


def _engine():
    return create_engine(get_settings().database_url_sync)


def _load_run(run_id: str) -> Optional[RunOut]:
    with _engine().connect() as conn:
        run_row = conn.execute(
            text(
                """
                SELECT id, file_id, user_id, template_name, state,
                       cost_estimated_usd, cost_actual_usd, cost_reserved_usd, error
                  FROM pipeline_runs WHERE id = :id
                """
            ),
            {"id": run_id},
        ).fetchone()
        if not run_row:
            return None

        step_rows = conn.execute(
            text(
                """
                SELECT id, name, agent_type, state, attempt, requires_review,
                       inputs_json, outputs_json, error, cost_usd
                  FROM pipeline_steps WHERE run_id = :id ORDER BY created_at ASC
                """
            ),
            {"id": run_id},
        ).fetchall()

    steps: list[StepOut] = [
        StepOut(
            id=r[0],
            name=r[1],
            agent_type=r[2],
            state=r[3],
            attempt=int(r[4] or 0),
            requires_review=bool(r[5]),
            inputs_json=r[6],
            outputs_json=r[7],
            error=r[8],
            cost_usd=float(r[9] or 0.0),
        )
        for r in step_rows
    ]
    return RunOut(
        id=run_row[0],
        file_id=run_row[1],
        user_id=run_row[2],
        template_name=run_row[3],
        state=run_row[4],
        cost_estimated_usd=float(run_row[5] or 0.0),
        cost_actual_usd=float(run_row[6] or 0.0),
        cost_reserved_usd=float(run_row[7] or 0.0),
        error=run_row[8],
        steps=steps,
    )


def _ensure_run_owner(run_id: str, user_id: str) -> None:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT user_id FROM pipeline_runs WHERE id = :id"),
            {"id": run_id},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="run not found")
    if row[0] and row[0] != user_id:
        raise HTTPException(status_code=403, detail="not your run")


# ── routes ────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_writer_required],
)
async def start_pipeline(
    body: StartPipelineRequest,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> RunOut:
    graph = body.custom_graph or pipeline_templates.get_template(body.template_name)
    if not graph:
        raise HTTPException(status_code=400, detail=f"unknown template: {body.template_name}")

    run_inputs: dict[str, Any] = {"brief": body.brief or {}}
    if body.target_topic is not None:
        run_inputs["target_topic"] = body.target_topic

    # ── 1) 预估
    estimate = estimate_pipeline_cost(
        graph=graph,
        brief=body.brief or {},
        user_id=current_user.id,
        file_id=body.file_id,
    )

    # ── 2) 解析 tenant + 并发上限（v2：从 user 升级到 tenant 维度）
    tctx = pipeline_tenant.resolve_tenant_context(
        current_user.id,
        file_id=body.file_id,
        user_plan=getattr(current_user, "plan", None) or "free",
    )
    snap = get_or_create_tenant(
        tctx.tenant_id, plan=tctx.plan, display_name=tctx.display_name
    )
    active = count_active_runs_tenant(tctx.tenant_id)
    if active >= snap.concurrent_max:
        raise HTTPException(
            status_code=429,
            detail=(
                f"concurrent runs limit reached: {active}/{snap.concurrent_max} "
                f"(tenant={tctx.tenant_id}); 请等已有 run 完成或 cancel 后再启动"
            ),
        )

    # ── 3) 配额预扣（reserve = total_usd）
    # Track-25：把 current_user.id 透传给 reserve_tenant，超限时它会先在
    # `user:{user_id}` 频道推 quota_exceeded 事件再让 router 抛 402，让前端
    # 全局 hook 立刻弹 toast，避免「点了启动突然 402」的困惑。
    reserved = float(estimate["total_usd"])
    rr = reserve_tenant(
        tctx.tenant_id,
        reserved,
        plan=tctx.plan,
        display_name=tctx.display_name,
        user_id=current_user.id,
    )
    if not rr.ok:
        raise HTTPException(status_code=402, detail=rr.reason or "quota check failed")

    # ── 4) 启动
    try:
        run_id = start_run(
            user_id=current_user.id,
            file_id=body.file_id,
            template_name=body.template_name,
            graph=graph,
            inputs=run_inputs,
            cost_estimated_usd=reserved,
            cost_reserved_usd=reserved,
            tenant_id=tctx.tenant_id,
        )
    except Exception:
        # 启动失败把刚才预扣的额度退回去
        release_tenant(tctx.tenant_id, reserved)
        raise

    _schedule_tick(run_id, background_tasks)

    out = _load_run(run_id)
    assert out is not None
    return out


@router.get("/quota", response_model=QuotaOut)
async def get_quota(current_user: CurrentUser) -> QuotaOut:
    tctx = pipeline_tenant.resolve_tenant_context(
        current_user.id, user_plan=getattr(current_user, "plan", None) or "free"
    )
    snap = get_or_create_tenant(
        tctx.tenant_id, plan=tctx.plan, display_name=tctx.display_name
    )
    active = count_active_runs_tenant(tctx.tenant_id)
    buckets = pipeline_buckets.list_buckets(tctx.tenant_id)
    return _quota_to_out(snap, active, tctx, buckets)


@router.get("/buckets", response_model=list[ProviderBucketOut])
async def get_provider_buckets(current_user: CurrentUser) -> list[ProviderBucketOut]:
    """配额 v2 专属：列出当前 tenant 的 provider 并发桶。

    用于前端「Provider 并发」面板按需轮询；当前桶为空时返回空 list（前端可降级到
    plan 默认值预览，或不渲染）。
    """
    tctx = pipeline_tenant.resolve_tenant_context(
        current_user.id, user_plan=getattr(current_user, "plan", None) or "free"
    )
    return [
        ProviderBucketOut(
            provider_name=b.provider_name,
            current_in_flight=b.current_in_flight,
            max_concurrent=b.max_concurrent,
            remaining=b.remaining,
            utilization_pct=round(b.utilization_pct, 1),
        )
        for b in pipeline_buckets.list_buckets(tctx.tenant_id)
    ]


@router.post("/estimate", response_model=CostEstimateOut)
async def estimate_pipeline(
    body: StartPipelineRequest,
    current_user: CurrentUser,
) -> CostEstimateOut:
    graph = body.custom_graph or pipeline_templates.get_template(body.template_name)
    if not graph:
        raise HTTPException(
            status_code=400, detail=f"unknown template: {body.template_name}"
        )
    estimate = estimate_pipeline_cost(
        graph=graph,
        brief=body.brief or {},
        user_id=current_user.id,
        file_id=body.file_id,
    )
    return CostEstimateOut(
        total_usd=float(estimate["total_usd"]),
        by_step=estimate["by_step"],
        missing_agents=estimate.get("missing_agents") or [],
    )


def _quota_to_out(
    snap: TenantQuotaSnapshot,
    active: int,
    tctx: pipeline_tenant.TenantContext,
    buckets: list[pipeline_buckets.BucketSnapshot],
) -> QuotaOut:
    return QuotaOut(
        monthly_limit_usd=snap.monthly_limit_usd,
        current_period_usage_usd=snap.current_period_usage_usd,
        remaining_usd=snap.remaining_usd,
        current_period_start=snap.current_period_start.isoformat(),
        concurrent_max=snap.concurrent_max,
        active_runs=active,
        tenant_id=tctx.tenant_id,
        tenant_plan=tctx.plan,
        tenant_display_name=snap.display_name or tctx.display_name,
        provider_buckets=[
            ProviderBucketOut(
                provider_name=b.provider_name,
                current_in_flight=b.current_in_flight,
                max_concurrent=b.max_concurrent,
                remaining=b.remaining,
                utilization_pct=round(b.utilization_pct, 1),
            )
            for b in buckets
        ],
    )


# ⚠️ /user-events 必须在 /{run_id} 之前注册（FastAPI 按声明顺序匹配；
# 否则 GET /user-events 会被 /{run_id} 吞掉，把 "user-events" 当 run_id 查 DB → 404）。
# helpers `_user_snapshot_payload` / `_user_events_sse_stream` 在文件后面定义，
# Python module 加载完所有 def 都在，handler 运行时才会调用，定义顺序无所谓。
@router.get("/user-events")
async def user_events_stream(
    current_user: CurrentUser,
    request: Request,
):
    """订阅当前登录用户的事件流（quota_exceeded / bucket_full）。

    全局 layout.tsx 挂 hook 即可监听，所有页面都能收到 toast；不需要每个
    pipeline 页面单独订阅。
    """

    tctx = pipeline_tenant.resolve_tenant_context(
        current_user.id, user_plan=getattr(current_user, "plan", None) or "free"
    )
    snap = get_or_create_tenant(
        tctx.tenant_id, plan=tctx.plan, display_name=tctx.display_name
    )
    active = count_active_runs_tenant(tctx.tenant_id)
    buckets = pipeline_buckets.list_buckets(tctx.tenant_id)
    snapshot_payload = _user_snapshot_payload(current_user, tctx, snap, active, buckets)

    last_event_id = request.headers.get("Last-Event-ID") or None
    return StreamingResponse(
        _user_events_sse_stream(
            current_user.id,
            request,
            snapshot_payload,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{run_id}", response_model=RunOut)
async def get_pipeline(run_id: str, current_user: CurrentUser) -> RunOut:
    _ensure_run_owner(run_id, current_user.id)
    out = _load_run(run_id)
    if not out:
        raise HTTPException(status_code=404, detail="run not found")
    return out


# ── SSE：替代 2.5s polling ───────────────────────────────────────────────────
# 协议：
#   event: snapshot      data: <RunOut JSON>             连接首条；前端用它对齐全量
#   event: step_state    data: <StepOut JSON + run_id>   单步状态变化（含 outputs / cost）
#   event: run_state     data: <RunOut JSON minus steps> run 顶层状态/成本变化
#   :ping                                                  注释行 heartbeat（25s）
#
# 前端断连重连时浏览器原生 EventSource 会自动重发 GET，本端会重新发 snapshot；
# 因此事件**不需要持久化**，redis pub/sub 即时投递即可。

_SSE_HEARTBEAT_SEC = 25.0
_SSE_MAX_DURATION_SEC = 30 * 60.0  # 兜底防止连接永远不释放


def _sse_format(
    event: str, data: dict[str, Any], *, event_id: str | None = None
) -> str:
    """格式化一条 SSE 事件。

    Track-17：可选 `event_id` 写到 `id:` 字段。浏览器原生 EventSource 会
    自动把最近一条 `id:` 缓存到内置 lastEventId，断网重连时通过
    `Last-Event-ID` 请求头送回服务端，让 backend 从断点续传 redis Stream。
    snapshot 是连接首条全量对齐，不来自 redis Stream，`event_id` 缺省 None。
    """

    head = f"id: {event_id}\n" if event_id else ""
    return (
        f"{head}event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


def _step_to_event_payload(step: "StepOut") -> dict[str, Any]:
    payload = step.model_dump()
    return payload


def _run_to_event_payload(run: "RunOut") -> dict[str, Any]:
    # run_state 不带 steps（事件流靠 step_state 单独维护 step 列表）
    payload = run.model_dump()
    payload.pop("steps", None)
    return payload


_TERMINAL_RUN_STATES = {"succeeded", "failed", "cancelled"}


async def _pipeline_sse_stream(
    run_id: str,
    request: Request,
    *,
    last_event_id: str | None = None,
) -> AsyncIterator[str]:
    """打开一个 SSE 流：snapshot → 订阅 redis 事件 → 终态后关闭。

    Track-17：`last_event_id` 来自请求头 `Last-Event-ID`（浏览器原生 EventSource
    断网重连时自动带）；非空时透传给 `pipeline_events.subscribe(...)` 让
    redis Stream 从断点继续推，不丢断网期间的事件。snapshot 仍照发，前端可以
    根据 stream 续传的 step_state / run_state 增量合并到 snapshot 上。

    断开条件（任一）：
    - 客户端断开（`request.is_disconnected`）
    - run 进入终态（succeeded/failed/cancelled）后再发完最后一条事件
    - 30 分钟超时兜底
    """
    snapshot = _load_run(run_id)
    if snapshot is None:
        yield _sse_format("error", {"detail": "run not found"})
        return
    yield _sse_format("snapshot", snapshot.model_dump())

    if snapshot.state in _TERMINAL_RUN_STATES:
        return

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _SSE_MAX_DURATION_SEC
    last_hb = loop.time()
    sub_iter = pipeline_events.subscribe(
        run_id, last_event_id=last_event_id, stop_event=stop_event
    )

    try:
        async for tick_msg in sub_iter:
            now = loop.time()
            if now > deadline:
                return
            if await request.is_disconnected():
                return

            if tick_msg is None:
                # idle tick（subscribe 内部 1s 一次）→ 距上次 heartbeat 超过阈值才发，避免每秒刷
                if now - last_hb >= _SSE_HEARTBEAT_SEC:
                    yield ": ping\n\n"
                    last_hb = now
                continue

            event_type, payload, event_id = tick_msg
            yield _sse_format(event_type, payload, event_id=event_id)
            last_hb = now

            # run 进入终态后给其他事件留 200ms 缓冲再断开
            if event_type == "run_state":
                state = payload.get("state")
                if isinstance(state, str) and state in _TERMINAL_RUN_STATES:
                    await asyncio.sleep(0.2)
                    return
    finally:
        stop_event.set()
        try:
            await sub_iter.aclose()  # type: ignore[attr-defined]
        except Exception:
            pass


@router.get("/{run_id}/events")
async def pipeline_events_stream(
    run_id: str,
    current_user: CurrentUser,
    request: Request,
):
    _ensure_run_owner(run_id, current_user.id)
    # Track-17：浏览器自动带的 Last-Event-ID 头透传给 subscribe → redis XREAD
    last_event_id = request.headers.get("Last-Event-ID") or None
    return StreamingResponse(
        _pipeline_sse_stream(run_id, request, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # 关掉 nginx / proxy 缓冲
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/{run_id}/tick", response_model=RunOut, dependencies=[_writer_required]
)
async def tick_pipeline(run_id: str, current_user: CurrentUser) -> RunOut:
    _ensure_run_owner(run_id, current_user.id)
    tick(run_id)
    out = _load_run(run_id)
    assert out is not None
    return out


@router.post(
    "/{run_id}/steps/{name}/rerun",
    response_model=StepOut,
    dependencies=[_writer_required],
)
async def rerun_pipeline_step(
    run_id: str,
    name: str,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> StepOut:
    _ensure_run_owner(run_id, current_user.id)
    step_id = _resolve_step_id(run_id, name)
    rerun_step(step_id)
    _schedule_tick(run_id, background_tasks)
    out = _load_run(run_id)
    assert out is not None
    return next(s for s in out.steps if s.id == step_id)


@router.post(
    "/{run_id}/steps/{name}/approve",
    response_model=RunOut,
    dependencies=[_writer_required],
)
async def approve_pipeline_step(
    run_id: str,
    name: str,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> RunOut:
    _ensure_run_owner(run_id, current_user.id)
    step_id = _resolve_step_id(run_id, name)
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE pipeline_steps
                   SET state = 'succeeded', finished_at = NOW(), error = NULL
                 WHERE id = :id AND state = 'awaiting_review'
                """
            ),
            {"id": step_id},
        )
    out = _load_run(run_id)
    assert out is not None
    # approve 直接改 DB 没走 runner —— 手动广播 step + run（state 可能从 awaiting_review→running）
    approved = next((s for s in out.steps if s.id == step_id), None)
    if approved is not None:
        pipeline_events.publish(run_id, "step_state", _step_to_event_payload(approved))
    pipeline_events.publish(run_id, "run_state", _run_to_event_payload(out))
    _schedule_tick(run_id, background_tasks)
    return out


@router.post(
    "/{run_id}/cancel", response_model=RunOut, dependencies=[_writer_required]
)
async def cancel_pipeline(run_id: str, current_user: CurrentUser) -> RunOut:
    _ensure_run_owner(run_id, current_user.id)
    refund_tenant_id: Optional[str] = None
    refund_amount: float = 0.0

    with _engine().begin() as conn:
        # 拿 run 当前 state，决定要不要退还
        row = conn.execute(
            text(
                """
                SELECT state, user_id, tenant_id, cost_reserved_usd
                  FROM pipeline_runs WHERE id = :id
                """
            ),
            {"id": run_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="run not found")
        prev_state, user_id, tenant_id, reserved = (
            row[0], row[1], row[2], float(row[3] or 0.0)
        )

        if prev_state not in ("succeeded", "failed", "cancelled"):
            # 累加 actual_cost = sum(steps.cost_usd)
            cost_row = conn.execute(
                text(
                    "SELECT COALESCE(SUM(cost_usd),0) FROM pipeline_steps WHERE run_id = :id"
                ),
                {"id": run_id},
            ).fetchone()
            actual_cost = float(cost_row[0] or 0.0) if cost_row else 0.0

            conn.execute(
                text(
                    """
                    UPDATE pipeline_runs
                       SET state='cancelled', finished_at=NOW(),
                           cost_actual_usd=:actual
                     WHERE id=:id
                    """
                ),
                {"id": run_id, "actual": actual_cost},
            )
            conn.execute(
                text(
                    """
                    UPDATE pipeline_steps SET state = 'cancelled'
                     WHERE run_id = :id
                       AND state IN ('pending','ready','running','awaiting_review')
                    """
                ),
                {"id": run_id},
            )

            refund = reserved - actual_cost
            if refund > 1e-6:
                # 优先 tenant_id（v2 新 run）；旧 run 没 tenant_id 时从 user_id 推一份
                effective_tid = tenant_id or (
                    pipeline_tenant.resolve_tenant_id(user_id) if user_id else None
                )
                if effective_tid:
                    refund_tenant_id = effective_tid
                    refund_amount = refund

    if refund_tenant_id and refund_amount > 0:
        try:
            release_tenant(refund_tenant_id, refund_amount)
        except Exception:  # pragma: no cover - 退还失败不阻断 cancel
            logger.exception(
                "release tenant quota failed tenant=%s refund=%s",
                refund_tenant_id,
                refund_amount,
            )

    out = _load_run(run_id)
    assert out is not None
    # cancel 改了 run + 所有未完成 step，前端要拿到这两类事件才能正确渲染
    pipeline_events.publish(run_id, "run_state", _run_to_event_payload(out))
    for step in out.steps:
        if step.state == "cancelled":
            pipeline_events.publish(run_id, "step_state", _step_to_event_payload(step))
    return out


def _resolve_step_id(run_id: str, name: str) -> str:
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT id FROM pipeline_steps WHERE run_id = :rid AND name = :name"),
            {"rid": run_id, "name": name},
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"step '{name}' not found")
    return row[0]


# ── Track-25：用户级 SSE（quota_exceeded / bucket_full） ─────────────────────
# 协议：
#   event: snapshot           data: <UserSnapshotOut JSON>     连接首条；当前 quota / 桶状态
#   event: quota_exceeded     data: {tenant_id, kind, message, attempted_cost,
#                                    monthly_limit, current_usage}
#   event: bucket_full        data: {tenant_id, kind, provider_name, message,
#                                    current_in_flight, max_concurrent}
#   :ping                                                       注释行 heartbeat（25s）
#
# 与 `/api/pipelines/{run_id}/events` 不同：本端点是「全局长连接」，没有终态，
# 浏览器原生 EventSource 离线重连时也会带 `Last-Event-ID`，redis Stream 续推。
# 30 分钟兜底关闭一次（防 nginx 超时 / 进程卡死），客户端会自动重连。


def _user_snapshot_payload(current_user, tctx, snap, active, buckets) -> dict[str, Any]:
    """连接时一次性的 quota + bucket 全量；与 `/quota` + `/buckets` 字段对齐。"""

    return {
        "user_id": current_user.id,
        "tenant_id": tctx.tenant_id,
        "tenant_plan": tctx.plan,
        "tenant_display_name": snap.display_name or tctx.display_name,
        "monthly_limit_usd": snap.monthly_limit_usd,
        "current_period_usage_usd": snap.current_period_usage_usd,
        "remaining_usd": snap.remaining_usd,
        "concurrent_max": snap.concurrent_max,
        "active_runs": active,
        "provider_buckets": [
            {
                "provider_name": b.provider_name,
                "current_in_flight": b.current_in_flight,
                "max_concurrent": b.max_concurrent,
                "remaining": b.remaining,
                "utilization_pct": round(b.utilization_pct, 1),
            }
            for b in buckets
        ],
    }


async def _user_events_sse_stream(
    user_id: str,
    request: Request,
    snapshot_payload: dict[str, Any],
    *,
    last_event_id: str | None = None,
) -> AsyncIterator[str]:
    """长连接 SSE：snapshot → 订阅 user channel → 增量推。

    与 pipeline run SSE 的差异：
    - 没有「run 进入终态自动关闭」逻辑；只到 30 分钟兜底 / 客户端断开
    - 任何 redis 抖动 / subscribe init 失败都安静关闭，浏览器自动重连
    """

    yield _sse_format("snapshot", snapshot_payload)

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    deadline = loop.time() + _SSE_MAX_DURATION_SEC
    last_hb = loop.time()
    sub_iter = pipeline_events.subscribe_user(
        user_id, last_event_id=last_event_id, stop_event=stop_event
    )

    try:
        async for tick_msg in sub_iter:
            now = loop.time()
            if now > deadline:
                return
            if await request.is_disconnected():
                return

            if tick_msg is None:
                if now - last_hb >= _SSE_HEARTBEAT_SEC:
                    yield ": ping\n\n"
                    last_hb = now
                continue

            event_type, payload, event_id = tick_msg
            yield _sse_format(event_type, payload, event_id=event_id)
            last_hb = now
    finally:
        stop_event.set()
        try:
            await sub_iter.aclose()  # type: ignore[attr-defined]
        except Exception:
            pass


# 触发 execute_step 名称导出，便于 Phase 2 切到 Celery 时 import
__all__ = ["router", "execute_step"]
