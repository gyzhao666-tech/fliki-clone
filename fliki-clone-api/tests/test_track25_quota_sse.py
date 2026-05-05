"""Track-25 · 配额超限 / Provider 桶满 SSE 实时推送 单元测试。

覆盖范围
--------
1. **publish_user_event 写到正确 channel** —— `user:{user_id}` 与既有
   `pipeline:run:` / `publish:plan:` 互斥；payload envelope `{type, data}`
   与现有 redis Stream / pub/sub 双写规约一致。
2. **reserve_tenant 超限抛事件** —— 真 PG 写入低额度 tenant，再 `reserve_tenant`
   超额时 `publish_user_event` 必须被调用一次，payload 至少含 `tenant_id` /
   `kind=monthly_quota` / `attempted_cost` / `monthly_limit` / `current_usage` /
   `message`；reservation 仍返 ok=False。
3. **acquire BucketFull 时抛事件** —— ensure_bucket(max=1) → acquire 第一次成功 →
   第二次必须抛 BucketFull 并先调 publish_user_event；payload 含 `provider_name`
   / `kind=bucket_full` / `current_in_flight` / `max_concurrent`。
4. **redis 不可用 noop** —— `_get_sync_client` 返 None 时 `publish_user_event`
   既不抛也不挂，业务主流程不受影响。
5. **subscribe_user 透传 last_event_id** —— `subscribe_user` 把 `Last-Event-ID`
   透传给 `_subscribe_channel(_user_channel(user_id))` → redis Stream 续传。

为什么这样测
------------
- `publish_user_event` 是事件发射器，独立于 reserve / acquire 业务逻辑；先证实
  它能把消息正确放到 channel 即可，业务侧只 mock 它断「被调用 + 参数正确」。
- reserve / acquire 的 PG 行为本身已被 quota_v2 测试覆盖；本测试只看
  「事件发射」这条新增链路，不重复 quota_v2 / bucket 测试已覆盖的语义。
"""
from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


# ── 路由顺序回归（修复 2026-05-05 19:35 发现的 404 bug）────────────────────
# /user-events 必须在 /{run_id} 之前注册，否则 FastAPI 按顺序匹配会让前者被
# 后者吞掉（GET /user-events → run_id="user-events" → DB 不存在 → 404）。
# T-25 agent 当时把 handler 加在文件末尾，FastAPI 按声明顺序注册路由就踩坑。

def test_user_events_registered_before_run_id_route():
    """openapi.json 路径列表里 `/pipelines/user-events` 必须存在且独立于
    `/pipelines/{run_id}`；如果路由顺序错了，user-events 会被 run_id 吃掉
    （openapi 还会显示存在，但运行时 404，所以这里附加 router.routes 顺序断言）。
    """
    from app.routers.pipelines import router

    # 收集 path -> 在 router.routes 中的 index
    path_index: dict[str, int] = {}
    for i, route in enumerate(router.routes):
        path = getattr(route, "path", None)
        if path and path not in path_index:
            path_index[path] = i
    # router 自带 prefix=/pipelines；route.path 是带 prefix 的完整路径
    ue = "/pipelines/user-events"
    rid = "/pipelines/{run_id}"
    assert ue in path_index, f"{ue} 路由没注册：{sorted(path_index.keys())}"
    assert rid in path_index, f"{rid} 路由没注册：{sorted(path_index.keys())}"
    assert path_index[ue] < path_index[rid], (
        f"{ue} 必须在 {rid} 之前注册，否则会被 path-param 吞成 404；"
        f"当前 user-events 在 #{path_index[ue]}，run_id 在 #{path_index[rid]}"
    )


# ── 1. publish_user_event channel routing ────────────────────────────────────


def test_publish_user_event_writes_to_user_channel() -> None:
    """`publish_user_event(user_id, ...)` 必须命中 `user:{user_id}` 频道，
    payload envelope 与既有 pipeline / publish 频道一致；不能误投到其它频道。
    """

    from app.services.pipeline import events as ev

    fake = MagicMock()
    with patch.object(ev, "_get_sync_client", return_value=fake):
        ev.publish_user_event(
            "demo-user-001",
            "quota_exceeded",
            {"tenant_id": "u:demo-user-001", "kind": "monthly_quota"},
        )

    # XADD：channel `user:demo-user-001` → stream key `user:demo-user-001:stream`
    fake.xadd.assert_called_once()
    args, kwargs = fake.xadd.call_args
    assert args[0] == "user:demo-user-001:stream"
    envelope = json.loads(args[1]["data"])
    assert envelope["type"] == "quota_exceeded"
    assert envelope["data"]["tenant_id"] == "u:demo-user-001"
    assert kwargs.get("maxlen") == 1000
    assert kwargs.get("approximate") is True

    # PUBLISH：兼容期保留路径，channel 名一致（无 :stream 后缀）
    fake.publish.assert_called_once()
    pub_args = fake.publish.call_args.args
    assert pub_args[0] == "user:demo-user-001"
    assert json.loads(pub_args[1]) == envelope


def test_publish_user_event_empty_user_id_is_noop() -> None:
    """user_id 为空（匿名上下文）时不应触发任何 publish——避免污染 redis 频道
    或把空字符串当 channel name 传给 redis。"""

    from app.services.pipeline import events as ev

    fake = MagicMock()
    with patch.object(ev, "_get_sync_client", return_value=fake):
        ev.publish_user_event("", "quota_exceeded", {"k": 1})
        ev.publish_user_event(None, "quota_exceeded", {"k": 1})  # type: ignore[arg-type]

    fake.xadd.assert_not_called()
    fake.publish.assert_not_called()


def test_publish_user_event_redis_unavailable_is_noop() -> None:
    """sync redis 不可用时（CI / dev 没起 redis）`publish_user_event` 不应
    阻塞主流程；reserve / acquire 即使后续抛业务异常也不能被这个路径污染。"""

    from app.services.pipeline import events as ev

    with patch.object(ev, "_get_sync_client", return_value=None):
        # 不抛即 PASS
        ev.publish_user_event("u-1", "quota_exceeded", {"x": 1})
        ev.publish_user_event("u-2", "bucket_full", {"y": 2})


# ── 2. reserve_tenant 超限抛 quota_exceeded ───────────────────────────────────


@pytest.mark.integration
def test_reserve_tenant_publishes_quota_exceeded_on_overrun(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tenant 月额 5 美元，预扣 4 + 再预扣 2 → 第二次必超；这时 reserve_tenant
    必须先调 publish_user_event(quota_exceeded, ...) 再返 ok=False。"""

    from app.services.pipeline import events as ev_module
    from app.services.pipeline import quota

    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    user_id = f"test_u_{uuid.uuid4().hex[:8]}"

    # 手动起一个 free 桶（默认 monthly_limit_usd=10），然后改成 5 缩窄上限
    quota.get_or_create_tenant(tid, plan="free")
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE tenant_quotas SET monthly_limit_usd=5.0 WHERE tenant_id=:t"
            ),
            {"t": tid},
        )

    captured: list[tuple[str, str, dict[str, Any]]] = []

    def _capture(uid: str, evt: str, payload: dict[str, Any]) -> None:
        captured.append((uid, evt, payload))

    monkeypatch.setattr(ev_module, "publish_user_event", _capture)
    monkeypatch.setattr(quota, "publish_user_event", _capture, raising=False)
    # quota.reserve_tenant 是局部 import → 直接 patch events 模块即可
    # （quota.py 里 `from . import events as pipeline_events` 后再调
    # `pipeline_events.publish_user_event(...)`，monkeypatch ev_module 即生效）

    try:
        ok_first = quota.reserve_tenant(tid, 4.0, plan="free", user_id=user_id)
        assert ok_first.ok is True

        rejected = quota.reserve_tenant(tid, 2.0, plan="free", user_id=user_id)
        assert rejected.ok is False
        assert "insufficient" in (rejected.reason or "")

        assert len(captured) == 1, captured
        uid, evt, payload = captured[0]
        assert uid == user_id
        assert evt == "quota_exceeded"
        assert payload["tenant_id"] == tid
        assert payload["kind"] == "monthly_quota"
        assert payload["attempted_cost"] == pytest.approx(2.0)
        assert payload["monthly_limit"] == pytest.approx(5.0)
        assert payload["current_usage"] == pytest.approx(4.0)
        assert "message" in payload and payload["message"]
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM tenant_quotas WHERE tenant_id=:t"), {"t": tid})


@pytest.mark.integration
def test_reserve_tenant_no_user_id_does_not_publish(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """老调用方不传 user_id 时，超限仍要返 ok=False，但**不**触发 publish（避免
    在没人监听 / 没法定位用户的路径上往 redis 喷垃圾事件）。"""

    from app.services.pipeline import events as ev_module
    from app.services.pipeline import quota

    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    quota.get_or_create_tenant(tid, plan="free")
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE tenant_quotas SET monthly_limit_usd=1.0 WHERE tenant_id=:t"
            ),
            {"t": tid},
        )

    captured: list[Any] = []
    monkeypatch.setattr(
        ev_module,
        "publish_user_event",
        lambda *a, **kw: captured.append((a, kw)),
    )

    try:
        rejected = quota.reserve_tenant(tid, 5.0, plan="free")  # 不传 user_id
        assert rejected.ok is False
        assert captured == []
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM tenant_quotas WHERE tenant_id=:t"), {"t": tid})


# ── 3. acquire BucketFull 时抛 bucket_full ────────────────────────────────────


@pytest.mark.integration
def test_acquire_publishes_bucket_full_when_max_reached(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """把 (tenant, provider) 桶 max_concurrent 强行设成 1；第一次 acquire 拿走
    唯一槽位，第二次 acquire 必抛 BucketFull 且先广播 bucket_full 事件，
    payload 至少含 provider_name / current_in_flight / max_concurrent。

    选 `elevenlabs`：free plan 默认 max=1；这样第二次 acquire 进入 retry 路径调
    `ensure_bucket(plan="free")` 时不会被 plan 升级 bump 把 max 拉回 2，能稳定
    复现「桶满」场景。
    """

    from app.services.pipeline import events as ev_module
    from app.services.pipeline import provider_buckets as pb

    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    user_id = f"test_u_{uuid.uuid4().hex[:8]}"
    provider = "elevenlabs"

    pb.ensure_bucket(tid, provider, plan="free")  # free 默认就是 1，无需手改 max
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE provider_concurrency_buckets
                   SET current_in_flight=0
                 WHERE tenant_id=:t AND provider_name=:p
                """
            ),
            {"t": tid, "p": provider},
        )

    captured: list[tuple[str, str, dict[str, Any]]] = []
    monkeypatch.setattr(
        ev_module,
        "publish_user_event",
        lambda uid, evt, payload: captured.append((uid, evt, payload)),
    )

    try:
        snap1 = pb.acquire(tid, provider, plan="free", user_id=user_id)
        assert snap1.current_in_flight == 1
        assert captured == [], "首次 acquire 不应推 bucket_full"

        with pytest.raises(pb.BucketFull):
            pb.acquire(tid, provider, plan="free", user_id=user_id)

        assert len(captured) == 1, captured
        uid, evt, payload = captured[0]
        assert uid == user_id
        assert evt == "bucket_full"
        assert payload["tenant_id"] == tid
        assert payload["kind"] == "provider_bucket"
        assert payload["provider_name"] == provider
        assert payload["max_concurrent"] == 1
        # current_in_flight 在桶满那一刻应是 1（== max）
        assert payload["current_in_flight"] == 1
        assert "message" in payload and provider in payload["message"]
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM provider_concurrency_buckets WHERE tenant_id=:t"
                ),
                {"t": tid},
            )


@pytest.mark.integration
def test_acquire_no_user_id_does_not_publish_bucket_full(
    pg_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧调用方（没 user_id 上下文，例如 system task）触发 BucketFull 时不应
    publish——让 quota_exceeded / bucket_full 路径只服务真有用户监听的请求。"""

    from app.services.pipeline import events as ev_module
    from app.services.pipeline import provider_buckets as pb

    tid = f"test_t:{uuid.uuid4().hex[:12]}"
    provider = "kling"

    pb.ensure_bucket(tid, provider, plan="free")
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE provider_concurrency_buckets
                   SET max_concurrent=1, current_in_flight=1
                 WHERE tenant_id=:t AND provider_name=:p
                """
            ),
            {"t": tid, "p": provider},
        )

    captured: list[Any] = []
    monkeypatch.setattr(
        ev_module,
        "publish_user_event",
        lambda *a, **kw: captured.append((a, kw)),
    )

    try:
        with pytest.raises(pb.BucketFull):
            pb.acquire(tid, provider, plan="free")  # 不传 user_id
        assert captured == []
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM provider_concurrency_buckets WHERE tenant_id=:t"
                ),
                {"t": tid},
            )


# ── 4. subscribe_user：channel 名 + last_event_id 透传 ────────────────────────


@pytest.mark.asyncio
async def test_subscribe_user_targets_user_channel_with_last_event_id() -> None:
    """`subscribe_user(user_id, last_event_id=...)` 必须把 cursor 透传给
    `xread({user:{user_id}:stream: cursor}, ...)`，不能跑到 pipeline / publish 频道。"""

    from app.services.pipeline import events as ev

    fake = AsyncMock()
    fake.ping = AsyncMock(return_value=True)
    fake.aclose = AsyncMock()
    fake.xread = AsyncMock(return_value=[])

    fake_module = MagicMock()
    fake_module.from_url = MagicMock(return_value=fake)

    with patch.dict("sys.modules", {"redis.asyncio": fake_module}):
        agen = ev.subscribe_user(
            "demo-user-001", last_event_id="1700000000000-0"
        )
        item = await agen.__anext__()
        await agen.aclose()

    assert item is None  # idle
    first_call_args = fake.xread.call_args_list[0]
    assert first_call_args.args[0] == {
        "user:demo-user-001:stream": "1700000000000-0"
    }
    assert first_call_args.kwargs.get("block") == 1000


@pytest.mark.asyncio
async def test_subscribe_user_empty_user_id_is_empty_iterator() -> None:
    """`user_id` 为空时直接返空迭代器，不要去连 redis（避免 dev 没启 redis 时
    匿名页面也尝试连接 → 噪音 warning）。"""

    from app.services.pipeline import events as ev

    agen = ev.subscribe_user("")
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


# ── 5. 烟测：events.py 与 quota / provider_buckets 的导入闭合 ────────────────


def test_events_module_exports_publish_user_event_and_subscribe_user() -> None:
    """避免 __all__ 漏导出导致前端/路由 import 失败。"""

    from app.services.pipeline import events as ev

    assert "publish_user_event" in ev.__all__
    assert "subscribe_user" in ev.__all__
    assert callable(ev.publish_user_event)
    assert callable(ev.subscribe_user)
