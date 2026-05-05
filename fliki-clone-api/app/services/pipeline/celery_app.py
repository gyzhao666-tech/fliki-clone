"""Celery 实例：Phase 2 把 Pipeline 调度从 FastAPI BackgroundTasks 解放到独立 worker pool。

设计要点：
- 同一 Celery app 名 `fliki_pipeline`，broker 走 `settings.celery_broker_url`（默认 redis://localhost:6379/0）
- 队列分级：
  * `interactive`：研究 / 脚本 / 质检（低延迟，便于 user 等审批节点）
  * `media`     ：视频 / 美术 / 配音 / 剪辑（长任务，worker 起 1-2 个并发即可）
  * `default`   ：tick 调度器与兜底
- `task_acks_late=True` + `worker_prefetch_multiplier=1`：长任务挂掉时不丢 ack，避免 step 卡死
- 默认**不**启用 always_eager；要在 dev 不起 worker 时跑，由路由层的 `schedule_tick` dispatcher
  fallback 到 BackgroundTasks（更可控）

启动 worker：
    cd fliki-clone-api && \
    .venv/bin/celery -A app.services.pipeline.celery_app worker \
      --loglevel=info \
      -Q interactive,media,default \
      --concurrency=2

生产建议拆三个 worker（每队列独立并发 / 资源池）：
    .venv/bin/celery -A app.services.pipeline.celery_app worker -Q interactive --concurrency=4
    .venv/bin/celery -A app.services.pipeline.celery_app worker -Q media       --concurrency=2
    .venv/bin/celery -A app.services.pipeline.celery_app worker -Q default     --concurrency=2
"""
from __future__ import annotations

from celery import Celery

from app.config import get_settings


_settings = get_settings()


celery_app = Celery(
    "fliki_pipeline",
    broker=_settings.celery_broker_url,
    backend=_settings.celery_result_backend,
    include=["app.services.pipeline.tasks"],
)

celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    # 长任务策略
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # 失败重试默认基线（agent 任务可在 task 内部覆盖）
    task_default_retry_delay=10,
    task_max_retries=3,
)


# 队列路由：按 agent_type 分桶；media 类长任务专属一组 worker，避免阻塞 interactive
QUEUE_BY_AGENT: dict[str, str] = {
    "research": "interactive",
    "script": "interactive",
    "review": "interactive",
    "art": "media",
    "voice": "media",
    "video": "media",
    "edit": "media",
}


def queue_for_agent(agent_type: str) -> str:
    return QUEUE_BY_AGENT.get(agent_type, "default")
