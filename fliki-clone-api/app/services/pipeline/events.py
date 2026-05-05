"""Pipeline 事件总线（Redis Stream + pub/sub 双写；支持 Last-Event-ID 续传）。

Track-03 抽出「以 channel name 为 key」的小核心；pipeline run / publish_plan
两套上层 API 共用一份 redis 客户端 + 同一份 idle/取消循环。

Track-17 升级：在原有 redis pub/sub 之上新增 redis Stream（XADD + XREAD），让
SSE 客户端断网重连时通过 `Last-Event-ID` 头从断点恢复，浏览器原生 EventSource
已会自动续传该头部，不丢事件。

设计：
- **publish 双写**：每条事件先 `XADD {channel}:stream * data <json>`（`MAXLEN ~ 1000`
  approximate trim 保留最近 1000 条；够 ~6 个完整 run），再 `PUBLISH {channel}`
  到 pub/sub（兼容期保留，老消费者直接收即可，不强制升级）
- **subscribe 用 XREAD**：从 `last_event_id`（XREAD ID）起拉；缺省用 `$` 只接
  新事件，与原 pub/sub 行为一致；BLOCK 1000ms 短超时让 idle 时 `yield None`，
  让上层 SSE 端能检查断连/心跳/终态
- **频道命名**：
  * `pipeline:run:{run_id}`：pub/sub 频道；对应 stream `pipeline:run:{run_id}:stream`
  * `publish:plan:{plan_id}`：pub/sub 频道；对应 stream `publish:plan:{plan_id}:stream`
- redis 不可用 / 失败时只 warning，不阻塞主流程；XADD 与 PUBLISH 互不依赖

事件协议（SSE 端把 envelope.type 写到 `event:` 字段，stream_id 写到 `id:` 字段）：
- `step_state` ：单步状态变化（含 outputs/error/cost）       —— pipeline 频道
- `run_state`  ：run 状态变化（含 cost_actual_usd / cost_reserved_usd）—— pipeline 频道
- `snapshot`   ：连接时一次性的全量 RunOut（由 SSE 端点直接发；**不带 id**
                 因为不来自 redis Stream，断网重连不重发）
- `publish_plan_state`：发布计划状态变化（phase=running/completed/system_error
  + ok / status / external_id / error）—— **publish:plan:{id}** 频道
- `heartbeat`  ：保活（由 SSE 端点周期发，不走 publish）

为什么 Stream + pub/sub 双写而不是只 Stream：
- pub/sub 0-延迟 push（XREAD BLOCK 1s 仍有最大 1s 抖动），保留兼容路径
- 老消费者可以继续用 pub/sub，新消费者用 Stream 拿 `last_event_id` 续传
- 两条路径互相独立，任何一边失败不影响另一边

不做：
- 多客户端 fan-out 优化（XREAD 单 reader 已够；多客户端各 BLOCK 自然分摊）
- redis Stream 跨进程 consumer group（pipeline / publish 都是单 SSE 进程消费）
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


_STREAM_MAXLEN = 1000  # MAXLEN ~ 1000：足够覆盖一次完整 run（~150 step_state）+ 几次重连


def _channel(run_id: str) -> str:
    return f"pipeline:run:{run_id}"


def _plan_channel(plan_id: str) -> str:
    """Track-03：publish_plans SSE 通道（与 pipeline run 频道独立，避免互相打扰）。"""

    return f"publish:plan:{plan_id}"


def _user_channel(user_id: str) -> str:
    """Track-25：用户级配额/桶满事件通道（跨 run / 跨 plan）。

    与 `pipeline:run:{run_id}` / `publish:plan:{plan_id}` 互斥；
    一个用户全局一条通道，layout.tsx 全局挂一个 hook 即可监听
    `quota_exceeded` / `bucket_full`，避免每次启动 run 才能感知额度问题。
    """

    return f"user:{user_id}"


def _stream_key(channel: str) -> str:
    """Track-17：每个 pub/sub 频道对应一条 redis Stream，名字加 `:stream` 后缀。

    分开是因为 redis 5.0+ 的 XADD 与 PUBLISH 是两种不同 datatype，不能复用同一个 key。
    """

    return f"{channel}:stream"


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

    Track-17：双写 redis Stream + pub/sub。前者用于 Last-Event-ID 续传，
    后者保留兼容（订阅端已切到 Stream，pub/sub 仅作 fallback / 老消费者备用）。

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
    except Exception as exc:  # pragma: no cover - 业务异常
        logger.warning(
            "pipeline events: encode channel=%s type=%s failed: %s",
            channel,
            event_type,
            exc,
        )
        return

    # 1) XADD：持久化到 Stream，最多保留 1000 条；用 approximate trim 减少 CPU
    try:
        client.xadd(
            _stream_key(channel),
            {"data": msg},
            maxlen=_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as exc:  # pragma: no cover - 环境依赖
        logger.warning(
            "pipeline events: xadd channel=%s type=%s failed: %s",
            channel,
            event_type,
            exc,
        )

    # 2) PUBLISH：兼容期保留（任何一边失败不影响另一边的事件路径）
    try:
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


def publish_user_event(
    user_id: str, event_type: str, payload: dict[str, Any]
) -> None:
    """Track-25：把用户级事件推到 `user:{user_id}` 频道。

    使用场景：
    - quota.reserve_tenant 在抛 402 之前推 `quota_exceeded`
    - provider_buckets.acquire 在 BucketFull 时推 `bucket_full`

    设计：
    - 与 pipeline run / publish plan 互不打扰（独立 channel + 独立 stream key）
    - 不传 user_id（None / 空串）时静默 noop，避免把后端 publishing 异常放大到调用栈
    - redis 不可用时 `_publish_to_channel` 内部已 warning + noop
    """

    if not user_id:
        return
    _publish_to_channel(_user_channel(user_id), event_type, payload)


# ── subscribe (async) ─────────────────────────────────────────────────────────


async def _subscribe_channel(
    channel: str,
    *,
    last_event_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[Optional[tuple[str, dict[str, Any], Optional[str]]]]:
    """订阅指定 redis Stream；空闲时 `yield None` 作 idle tick。

    返回 3-tuple `(event_type, payload, event_id)`；`event_id` 是 redis Stream
    生成的 entry id（形如 `1700000000000-0`），SSE 端把它写到 `id:` 字段让
    浏览器在断网重连时自动带 `Last-Event-ID` 续传。

    Track-17 设计：
    - 用 `client.xread({stream_key: cursor}, block=1000)` 短超时阻塞拉取；
      没消息 → 返回空 list → `yield None`
    - `cursor` 起始：传入 `last_event_id` 时从该 id **之后**开始（XREAD 语义）；
      缺省 `$` 表示「只接连接后产生的新事件」，与原 pub/sub 行为对齐
    - 每条 entry 拿到后把 `cursor` 更新为 entry id，下轮从此处继续

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

    stream_key = _stream_key(channel)
    cursor: str = last_event_id or "$"

    client = None
    try:
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        # 探活；不成功就直接安静退出（与旧 pubsub.subscribe 失败语义一致）
        await client.ping()
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "pipeline events: subscribe init %s failed: %s", channel, exc
        )
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        return

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                return
            try:
                # block 单位 = 毫秒；count=None → 一次最多取所有可用 entries
                resp = await client.xread({stream_key: cursor}, block=1000)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "pipeline events: xread %s failed: %s", channel, exc
                )
                return
            if not resp:
                yield None  # idle tick：让调用方检查断连/心跳
                continue
            # resp = [(stream_key, [(entry_id, {field: value, ...}), ...])]
            try:
                _, entries = resp[0]
            except (TypeError, ValueError, IndexError):  # pragma: no cover
                continue
            for entry_id, fields in entries:
                cursor = entry_id
                if not isinstance(fields, dict):
                    continue
                data = fields.get("data")
                if not isinstance(data, str):
                    continue
                try:
                    envelope = json.loads(data)
                    event_type = envelope.get("type") or "message"
                    event_payload = envelope.get("data") or {}
                except Exception:
                    continue
                yield event_type, event_payload, entry_id
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def subscribe(
    run_id: str,
    *,
    last_event_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[Optional[tuple[str, dict[str, Any], Optional[str]]]]:
    """订阅某 pipeline run 的事件流。

    Track-17：新增 `last_event_id` 参数；HTTP 入口从 `Last-Event-ID` 头读取
    后透传，让断网重连客户端从断点恢复。
    """

    async for item in _subscribe_channel(
        _channel(run_id),
        last_event_id=last_event_id,
        stop_event=stop_event,
    ):
        yield item


async def subscribe_publish_plan(
    plan_id: str,
    *,
    last_event_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[Optional[tuple[str, dict[str, Any], Optional[str]]]]:
    """Track-03：订阅某 publish_plan 的 publish_plan_state 事件流。

    SSE 端点拿到的 (event_type, payload, event_id) 直接转 `id:`/`event:`/`data:`
    行下发；publish_plan_state 进入终态（`completed` / `system_error`）后
    SSE 端点需要主动断开（看 routers/production.py 的 `_publish_plan_sse_stream`）。

    Track-17：新增 `last_event_id` 透传，与 pipeline run 一致。
    """

    async for item in _subscribe_channel(
        _plan_channel(plan_id),
        last_event_id=last_event_id,
        stop_event=stop_event,
    ):
        yield item


async def subscribe_user(
    user_id: str,
    *,
    last_event_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> AsyncIterator[Optional[tuple[str, dict[str, Any], Optional[str]]]]:
    """Track-25：订阅 `user:{user_id}` 频道的用户级事件流。

    与 `subscribe` / `subscribe_publish_plan` 共用 `_subscribe_channel` 内核；
    SSE 端点拿到 `(event_type, payload, event_id)` 转下发即可。

    用户级 SSE 是「长连接 / 不主动终止」：只要客户端在线就一直挂着；
    路由层根据 30 分钟兜底 + 客户端断开自动结束。
    """

    if not user_id:
        return
    async for item in _subscribe_channel(
        _user_channel(user_id),
        last_event_id=last_event_id,
        stop_event=stop_event,
    ):
        yield item


__all__ = [
    "publish",
    "publish_plan_event",
    "publish_user_event",
    "subscribe",
    "subscribe_publish_plan",
    "subscribe_user",
]
