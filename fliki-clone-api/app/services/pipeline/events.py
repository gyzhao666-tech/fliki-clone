"""Pipeline 事件总线（Redis pub/sub）。

替换前端 2.5s polling 用的最小事件层：
- `publish(run_id, event_type, payload)`：**同步**调用，runner / Celery worker /
  路由都能直接喊；redis 不可用 / 失败时只 warning，不阻塞主流程
- `subscribe(run_id)`：FastAPI SSE 端点用的 async iterator；从 redis pub/sub 拉消息

为什么是 pub/sub 不是 LISTEN/NOTIFY 也不是 redis 轮询：
- pub/sub 跨进程（celery worker 跑 step 时也要能通知 web 进程的 SSE 客户端）
- 0 延迟（不像 scenes.py 用 redis 轮询有 2s 间隔）
- 已经在用 redis（celery broker），不再加新依赖

事件协议（SSE 端把它的 type 直接写到 `event:` 字段）：
- `step_state` ：单步状态变化（含 outputs/error/cost）
- `run_state`  ：run 状态变化（含 cost_actual_usd / cost_reserved_usd）
- `snapshot`   ：连接时一次性的全量 RunOut（由 SSE 端点直接发）
- `heartbeat`  ：保活（由 SSE 端点周期发，不走 publish）

设计取舍：
- 不持久化事件；前端断连重连靠 `snapshot` 重新对齐
- publish 用 sync redis client（runner 是同步代码）；subscribe 用 redis.asyncio
- 频道名 `pipeline:run:{run_id}`；同一 run 的所有事件共享，前端只订阅本 run
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


def publish(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """把一个事件推到本 run 的频道；任何异常只记 warning。

    `payload` 会被序列化为 JSON 字符串；包一层 envelope 以便消费端区分 type。
    """
    client = _get_sync_client()
    if client is None:
        return
    try:
        msg = json.dumps(
            {"type": event_type, "data": payload}, ensure_ascii=False, default=str
        )
        client.publish(_channel(run_id), msg)
    except Exception as exc:  # pragma: no cover - 环境依赖
        logger.warning(
            "pipeline events: publish run=%s type=%s failed: %s",
            run_id,
            event_type,
            exc,
        )


# ── subscribe (async) ─────────────────────────────────────────────────────────


async def subscribe(
    run_id: str, *, stop_event: Optional[asyncio.Event] = None
) -> AsyncIterator[Optional[tuple[str, dict[str, Any]]]]:
    """异步迭代某 run 的事件 `(event_type, payload)`；空闲时 `yield None` 作 idle tick。

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
        await pubsub.subscribe(_channel(run_id))
    except Exception as exc:  # pragma: no cover
        logger.warning("pipeline events: subscribe failed: %s", exc)
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
                logger.warning("pipeline events: get_message failed: %s", exc)
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
            await pubsub.unsubscribe(_channel(run_id))
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await client.aclose()
        except Exception:
            pass


__all__ = ["publish", "subscribe"]
