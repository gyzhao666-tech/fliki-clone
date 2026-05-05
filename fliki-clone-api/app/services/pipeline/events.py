"""Pipeline 事件总线（Redis pub/sub）。

替换前端 polling 用的最小事件层：
- `publish(run_id, event_type, payload)`：**同步**调用，runner / Celery worker /
  路由都能直接喊；redis 不可用 / 失败时只 warning，不阻塞主流程
- `subscribe(run_id)`：FastAPI SSE 端点用的 async iterator；从 redis pub/sub 拉消息

Track-03 扩展（publish 任务异步化）：
- 新增 `publish_plan_event(plan_id, event_type, payload)` /
  `subscribe_publish_plan(plan_id, ...)`：用 `publish:plan:{plan_id}` 频道
  让 publish_plans 也能走 SSE 推 status 流（draft → running → published / failed）
- 内部把 publish/subscribe 抽成「以 channel name 为 key」的小核心，再让两套
  上层 API（pipeline run / publish plan）共用同一份 redis 客户端 + 同一份 idle/取消
  循环；上层语义保持不变

为什么是 pub/sub 不是 LISTEN/NOTIFY 也不是 redis 轮询：
- pub/sub 跨进程（celery worker 跑 step / publish 时也要能通知 web 进程的 SSE 客户端）
- 0 延迟（不像 scenes.py 用 redis 轮询有 2s 间隔）
- 已经在用 redis（celery broker），不再加新依赖

事件协议（SSE 端把它的 type 直接写到 `event:` 字段）：
- `step_state` ：单步状态变化（含 outputs/error/cost）       —— pipeline 频道
- `run_state`  ：run 状态变化（含 cost_actual_usd / cost_reserved_usd）—— pipeline 频道
- `snapshot`   ：连接时一次性的全量 RunOut（由 SSE 端点直接发）—— pipeline 频道
- `publish_plan_state`：发布计划状态变化（phase=running/completed/system_error
  + ok / status / external_id / error）—— **publish:plan:{id}** 频道
- `heartbeat`  ：保活（由 SSE 端点周期发，不走 publish）

设计取舍：
- 不持久化事件；前端断连重连靠 `snapshot` 重新对齐
- publish 用 sync redis client（runner 是同步代码）；subscribe 用 redis.asyncio
- 频道名：
  * `pipeline:run:{run_id}`：同一 run 的所有 step / run_state 事件
  * `publish:plan:{plan_id}`：同一 plan 的 publish_plan_state 事件
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


def _channel(run_id: str) -> str:
    return f"pipeline:run:{run_id}"


def _plan_channel(plan_id: str) -> str:
    """Track-03：publish_plans SSE 通道（与 pipeline run 频道独立，避免互相打扰）。"""

    return f"publish:plan:{plan_id}"


# ── publish (sync) ────────────────────────────────────────────────────────────

_sync_client = None  # 懒初始化的 sync redis client


def _get_sync_client():
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    try:
        import redis  # sync client（已在 requirements）

        _sync_client = redis.Redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
        # 探活，避免后续每次 publish 才发现 redis 挂了
        _sync_client.ping()
    except Exception as exc:  # pragma: no cover - 环境依赖
        logger.warning("pipeline events: sync redis init failed: %s", exc)
        _sync_client = None
    return _sync_client


def _publish_to_channel(
    channel: str, event_type: str, payload: dict[str, Any]
) -> None:
    """把事件推到指定 redis 频道；任何异常只记 warning。

    `payload` 序列化为 JSON；包一层 envelope `{"type": ..., "data": ...}` 让
    消费端区分 type，与 pipeline / publish 共用一套消息格式。
    """

    client = _get_sync_client()
    if client is None:
        return
    try:
        msg = json.dumps(
            {"type": event_type, "data": payload}, ensure_ascii=False, default=str
        )
        client.publish(channel, msg)
    except Exception as exc:  # pragma: no cover - 环境依赖
        logger.warning(
            "pipeline events: publish channel=%s type=%s failed: %s",
            channel,
            event_type,
            exc,
        )


def publish(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """把一个事件推到本 run 的频道。"""

    _publish_to_channel(_channel(run_id), event_type, payload)


def publish_plan_event(
    plan_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    """Track-03：把一个事件推到 publish_plan 频道。

    典型 event_type 是 `publish_plan_state`；payload 见 SSE 协议注释。
    """

    _publish_to_channel(_plan_channel(plan_id), event_type, payload)


# ── subscribe (async) ─────────────────────────────────────────────────────────


async def _subscribe_channel(
    channel: str, *, stop_event: Optional[asyncio.Event] = None
) -> AsyncIterator[Optional[tuple[str, dict[str, Any]]]]:
    """订阅指定 redis 频道；空闲时 `yield None` 作 idle tick。

    设计：
    - 用 `pubsub.get_message(timeout=1.0)` 短超时拉取 → 没消息时 `yield None`
    - 这样调用方（SSE 端点）能用普通 `async for` 检查断连/心跳/终态，
      避免 `asyncio.wait_for(__anext__)` 取消正在进行的 redis 请求带来的状态不确定

    退出条件：
    - 调用方 `aclose()`
    - `stop_event.set()`
    - redis 出错（安静返回，调用方下次 anext 拿到 StopAsyncIteration）
    """
    try:
        import redis.asyncio as aioredis
    except Exception as exc:  # pragma: no cover - 环境依赖
        logger.warning("pipeline events: redis.asyncio unavailable: %s", exc)
        return

    try:
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
    except Exception as exc:  # pragma: no cover
        logger.warning("pipeline events: subscribe %s failed: %s", channel, exc)
        try:
            await client.aclose()  # type: ignore[name-defined]
        except Exception:
            pass
        return

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "pipeline events: get_message %s failed: %s", channel, exc
                )
                return
            if msg is None:
                yield None  # idle tick：让调用方检查断连/心跳
                continue
            data = msg.get("data")
            if not isinstance(data, str):
                continue
            try:
                envelope = json.loads(data)
                event_type = envelope.get("type") or "message"
                payload = envelope.get("data") or {}
            except Exception:
                continue
            yield event_type, payload
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await client.aclose()
        except Exception:
            pass


async def subscribe(
    run_id: str, *, stop_event: Optional[asyncio.Event] = None
) -> AsyncIterator[Optional[tuple[str, dict[str, Any]]]]:
    """订阅某 pipeline run 的事件流。"""

    async for item in _subscribe_channel(_channel(run_id), stop_event=stop_event):
        yield item


async def subscribe_publish_plan(
    plan_id: str, *, stop_event: Optional[asyncio.Event] = None
) -> AsyncIterator[Optional[tuple[str, dict[str, Any]]]]:
    """Track-03：订阅某 publish_plan 的 publish_plan_state 事件流。

    SSE 端点拿到的 (event_type, payload) 直接转 `event:` / `data:` 行下发；
    publish_plan_state 进入终态（`completed` / `system_error`）后 SSE 端点
    需要主动断开（看 routers/production.py 的 `_publish_plan_sse_stream`）。
    """

    async for item in _subscribe_channel(
        _plan_channel(plan_id), stop_event=stop_event
    ):
        yield item


__all__ = [
    "publish",
    "publish_plan_event",
    "subscribe",
    "subscribe_publish_plan",
]
