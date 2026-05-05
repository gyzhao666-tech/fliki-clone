"""Track-17 · SSE 断网重连 last_event_id 续传 单元测试。

覆盖三个层面：
1. **publish 双写**：`_publish_to_channel` 同时调 XADD（含 MAXLEN ~ 1000）+ PUBLISH。
2. **subscribe XREAD**：`_subscribe_channel` 把 `last_event_id` 透传给
   `client.xread(block=...)`，envelope 带 `event_id` 单调递增；缺省用 `$`。
3. **SSE 格式**：`_sse_format(event, data, event_id=...)` 在 `event_id` 非空时
   prepend `id: <event_id>\\n`，让浏览器原生 EventSource 在断网重连时自动带
   `Last-Event-ID` 续传。

Mock 思路：
- 不依赖真 redis，全程用 `MagicMock` / `AsyncMock` 替换 `_get_sync_client` 与
  `redis.asyncio.from_url`，断言关键参数 / yield 顺序。
- `pytest.mark.asyncio` 用 strict 模式（pytest.ini 已配），async case 显式标。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. publish 双写 ───────────────────────────────────────────────────────────


def test_publish_to_channel_writes_xadd_and_pubsub() -> None:
    """publish 应同时写 redis Stream（持久化 + Last-Event-ID 续传源）和
    pub/sub（兼容旧消费者 / 0-延迟 push）。任何一边失败不影响另一边——
    这里只验「都被调用 + 关键参数正确」。"""

    from app.services.pipeline import events as ev

    fake = MagicMock()
    with patch.object(ev, "_get_sync_client", return_value=fake):
        ev._publish_to_channel(
            "pipeline:run:r1", "step_state", {"state": "running"}
        )

    # XADD：MAXLEN ~ 1000 approximate trim 是 Track-17 设计上界（覆盖 ~6 个完整 run）
    fake.xadd.assert_called_once()
    args, kwargs = fake.xadd.call_args
    assert args[0] == "pipeline:run:r1:stream"  # stream key 加 :stream 后缀
    assert "data" in args[1]
    envelope = json.loads(args[1]["data"])
    assert envelope == {"type": "step_state", "data": {"state": "running"}}
    assert kwargs.get("maxlen") == 1000
    assert kwargs.get("approximate") is True

    # PUBLISH：保留兼容路径
    fake.publish.assert_called_once()
    pub_args = fake.publish.call_args.args
    assert pub_args[0] == "pipeline:run:r1"  # pub/sub 频道名（无 :stream 后缀）
    assert json.loads(pub_args[1]) == envelope


def test_publish_xadd_failure_does_not_break_pubsub() -> None:
    """XADD 抛异常时仍要走 PUBLISH——双写互不依赖；redis Stream 暂时不可
    用（rev < 5.0 / OOM 等）也别让现有 pub/sub 消费者断流。"""

    from app.services.pipeline import events as ev

    fake = MagicMock()
    fake.xadd.side_effect = RuntimeError("simulated XADD outage")
    with patch.object(ev, "_get_sync_client", return_value=fake):
        ev._publish_to_channel(
            "publish:plan:p1", "publish_plan_state", {"phase": "running"}
        )
    fake.xadd.assert_called_once()
    fake.publish.assert_called_once()


def test_publish_with_no_redis_client_is_noop() -> None:
    """sync redis 不可用时双写都跳过，外部主流程不应感知。"""

    from app.services.pipeline import events as ev

    with patch.object(ev, "_get_sync_client", return_value=None):
        # 不抛异常即 PASS
        ev._publish_to_channel("pipeline:run:r1", "step_state", {"x": 1})


# ── 2. subscribe XREAD + last_event_id 续传 ───────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_passes_last_event_id_to_xread_and_yields_id() -> None:
    """传入 `last_event_id` 时，第一次 XREAD 必须带该 id 起点；
    收到的事件 envelope 携带 entry_id 让 SSE 端 emit `id:` 字段。"""

    from app.services.pipeline import events as ev

    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    # 第一次 xread 返一条事件；第二次返 None 模拟 idle；第三次抛 StopAsync
    payloads = [
        [
            (
                "pipeline:run:r1:stream",
                [
                    (
                        "1700000000000-0",
                        {
                            "data": json.dumps(
                                {
                                    "type": "step_state",
                                    "data": {"state": "running"},
                                }
                            )
                        },
                    )
                ],
            )
        ],
        [],  # idle
        [
            (
                "pipeline:run:r1:stream",
                [
                    (
                        "1700000000005-0",
                        {
                            "data": json.dumps(
                                {
                                    "type": "run_state",
                                    "data": {"state": "succeeded"},
                                }
                            )
                        },
                    )
                ],
            )
        ],
    ]
    fake.xread = AsyncMock(side_effect=payloads + [[]])

    fake_module = MagicMock()
    fake_module.from_url = MagicMock(return_value=fake)

    with patch.dict("sys.modules", {"redis.asyncio": fake_module}):
        items = []
        agen = ev._subscribe_channel(
            "pipeline:run:r1", last_event_id="1699999999999-0"
        )
        # 拉 4 个 yield：事件1 / idle / 事件2 / idle
        for _ in range(4):
            try:
                item = await agen.__anext__()
            except StopAsyncIteration:
                break
            items.append(item)
        await agen.aclose()

    # 第一次 xread 必须以传入的 last_event_id 为起点（不是默认 $）
    first_call_args = fake.xread.call_args_list[0]
    streams_arg = first_call_args.args[0]
    assert streams_arg == {"pipeline:run:r1:stream": "1699999999999-0"}
    assert first_call_args.kwargs.get("block") == 1000

    # 第二次 xread 起点应是「最后一条 entry id」（cursor 推进），不是原 last_event_id
    assert (
        fake.xread.call_args_list[1].args[0]
        == {"pipeline:run:r1:stream": "1700000000000-0"}
    )

    # yield 顺序：(event_type, payload, entry_id) → None → (...) → None
    assert items[0] == (
        "step_state",
        {"state": "running"},
        "1700000000000-0",
    )
    assert items[1] is None
    assert items[2] == (
        "run_state",
        {"state": "succeeded"},
        "1700000000005-0",
    )
    assert items[3] is None

    # 单调递增：entry_id 只可能往前，不能回退
    ids = [it[2] for it in items if it is not None]
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_subscribe_default_cursor_is_dollar_sign() -> None:
    """缺省 last_event_id 用 `$` 表示「只接连接后产生的新事件」，与原 pub/sub
    行为一致；非旧客户端首次连接不应被翻历史回放淹没。"""

    from app.services.pipeline import events as ev

    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    fake.xread = AsyncMock(return_value=[])

    fake_module = MagicMock()
    fake_module.from_url = MagicMock(return_value=fake)

    with patch.dict("sys.modules", {"redis.asyncio": fake_module}):
        agen = ev._subscribe_channel("publish:plan:p1")  # 不传 last_event_id
        item = await agen.__anext__()  # idle yield None
        await agen.aclose()

    assert item is None
    first_call_args = fake.xread.call_args_list[0]
    assert first_call_args.args[0] == {"publish:plan:p1:stream": "$"}


@pytest.mark.asyncio
async def test_subscribe_redis_init_failure_is_silent() -> None:
    """redis ping 失败时 subscribe 应安静退出（StopAsyncIteration）；调用方下次
    anext 终止循环，SSE 端会平稳关闭——避免把 redis 抖动放大成 500。"""

    from app.services.pipeline import events as ev

    fake = AsyncMock()
    fake.ping = AsyncMock(side_effect=RuntimeError("conn refused"))
    fake.aclose = AsyncMock()

    fake_module = MagicMock()
    fake_module.from_url = MagicMock(return_value=fake)

    with patch.dict("sys.modules", {"redis.asyncio": fake_module}):
        agen = ev._subscribe_channel("pipeline:run:r1")
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


# ── 3. SSE 格式：id: 字段 ────────────────────────────────────────────────────


def test_sse_format_emits_id_when_event_id_present_pipeline() -> None:
    """`pipelines.py::_sse_format(event_id=...)` 必须先 emit `id:` 再 `event:`，
    浏览器原生 EventSource 才能把 id 缓存到 lastEventId 用于断网重连。"""

    from app.routers.pipelines import _sse_format

    out = _sse_format(
        "step_state", {"state": "running"}, event_id="1700000000000-0"
    )
    # 顺序：id: 在 event: 之前；以双换行结束
    assert out.startswith("id: 1700000000000-0\nevent: step_state\n")
    assert out.endswith("\n\n")
    # data 行 JSON 仍可解析
    data_line = [l for l in out.splitlines() if l.startswith("data: ")][0]
    assert json.loads(data_line[len("data: ") :]) == {"state": "running"}


def test_sse_format_skips_id_when_none_pipeline() -> None:
    """snapshot 是 SSE 端点直接生成的全量对齐，不来自 redis Stream，不应带
    id 字段（带了也不影响功能，但纯粹起来更准确——浏览器只会把最后一条 id
    缓存为 lastEventId，snapshot 的 id 无意义）。"""

    from app.routers.pipelines import _sse_format

    out = _sse_format("snapshot", {"id": "r1"})
    assert "\nid: " not in "\n" + out
    assert out.startswith("event: snapshot\n")


def test_sse_format_emits_id_when_event_id_present_production() -> None:
    """同样的验证作用在 production 路由（publish_plan_state）。"""

    from app.routers.production import _sse_format

    out = _sse_format(
        "publish_plan_state",
        {"phase": "running"},
        event_id="1700000000123-0",
    )
    assert out.startswith("id: 1700000000123-0\nevent: publish_plan_state\n")
    assert out.endswith("\n\n")


def test_sse_format_skips_id_when_none_production() -> None:
    from app.routers.production import _sse_format

    out = _sse_format("snapshot", {"id": "p1"})
    assert "\nid: " not in "\n" + out
    assert out.startswith("event: snapshot\n")
