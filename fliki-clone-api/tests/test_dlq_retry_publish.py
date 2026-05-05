"""Track-15：DLQ retry 识别 ``publish.execute_plan`` task。

背景
----
Track-03 publish 异步化后，publish 死信的 ``task_name`` 是 ``publish.execute_plan``，
``args=[plan_id]``，``kwargs={"user_id": ...}``，且**不带 run_id**（publish_plans 与
pipeline_runs 没有外键关联）。

旧版 ``_retry_dispatch(run_id, bg)`` 只接 run_id，且固定派给 ``tick_task``：
- 对 publish 死信：先在 router 入口被 ``run_id is None`` 直接 400 拒绝
- 即使 router 不拦，丢进 tick_task 也是「调度一个不存在的 run」→ 立刻 settle，
  发布从未真重投
- DLQ 行被标 retried 但产生了静默失败

修复后 ``_retry_dispatch(dead, bg)`` 按 task_name 分支：
- ``publish.execute_plan`` → ``execute_publish_plan_task.apply_async`` /
  ``_publish_execute_with_events``（celery / BackgroundTasks 双路径与 router execute 一致）
- 其余（含 ``pipeline.tick`` / ``pipeline.execute_step`` / ``background.tick``）→ tick_task

覆盖
----
1. ``test_retry_dispatch_publish_celery`` celery 路径：apply_async 收到正确 args/kwargs/queue
2. ``test_retry_dispatch_publish_background`` BackgroundTasks 路径：add_task 收到
   ``_publish_execute_with_events(plan_id, user_id)``
3. ``test_retry_dispatch_publish_kwargs_user_id_fallback`` 未传 kwargs.user_id 时
   fallback 到 dlq 行级 ``dead.user_id``
4. ``test_retry_dispatch_publish_missing_plan_id_400`` args + kwargs 都缺 plan_id → 400
5. ``test_retry_dispatch_tick_celery_unchanged`` tick 类死信：保持原 tick_task.delay 行为
6. ``test_retry_dispatch_tick_background_unchanged`` tick 类死信 BackgroundTasks 路径
7. ``test_retry_dispatch_tick_no_run_id_400`` 非 publish 类且缺 run_id → 400
   （回归保护，旧路径错误信息更详细带 task_name）
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import BackgroundTasks, HTTPException

pytestmark = pytest.mark.unit


# ── helpers ────────────────────────────────────────────────────────────────


def _settings(*, celery_enabled: bool) -> SimpleNamespace:
    """最小 settings 替身；``_retry_dispatch`` 只读 ``celery_enabled``。"""

    return SimpleNamespace(celery_enabled=celery_enabled)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, *, celery_enabled: bool) -> None:
    """覆盖 ``app.routers.dlq`` 模块内被绑定的 ``get_settings`` 符号。"""

    from app.routers import dlq as dlq_mod

    monkeypatch.setattr(
        dlq_mod, "get_settings", lambda: _settings(celery_enabled=celery_enabled)
    )


def _publish_dead(
    *,
    args_json: list[Any] | None = None,
    kwargs_json: dict[str, Any] | None = None,
    user_id: str | None = "u-publisher",
) -> dict[str, Any]:
    """构造一条 publish.execute_plan 死信（与 ``_publish_execute_with_events`` push 同形）。"""

    return {
        "id": "dlq-1",
        "task_name": "publish.execute_plan",
        "args_json": args_json if args_json is not None else ["plan-abc"],
        "kwargs_json": (
            kwargs_json if kwargs_json is not None else {"user_id": user_id}
        ),
        "run_id": None,  # publish 死信结构性无 run_id
        "step_id": None,
        "user_id": user_id,
        "status": "pending",
    }


# ── 1. publish celery 路径 ─────────────────────────────────────────────────


def test_retry_dispatch_publish_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """celery_enabled=True 时直接派 ``execute_publish_plan_task.apply_async``。"""
    from app.routers.dlq import _retry_dispatch
    from app.services.pipeline import tasks as tasks_mod

    _patch_settings(monkeypatch, celery_enabled=True)

    captured: dict[str, Any] = {}

    def fake_apply_async(*args: Any, **kwargs: Any) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        tasks_mod.execute_publish_plan_task, "apply_async", fake_apply_async
    )

    bg = BackgroundTasks()
    dispatcher = _retry_dispatch(
        _publish_dead(args_json=["plan-xyz"], kwargs_json={"user_id": "u-7"}),
        bg,
    )

    assert dispatcher == "celery"
    # apply_async(*args=(), kwargs={'args': ['plan-xyz'], 'kwargs': {...}, 'queue': 'default'})
    assert captured["kwargs"]["args"] == ["plan-xyz"]
    assert captured["kwargs"]["kwargs"] == {"user_id": "u-7"}
    assert captured["kwargs"]["queue"] == "default"
    # 别误把 publish 死信塞给 BackgroundTasks
    assert bg.tasks == []


# ── 2. publish BackgroundTasks 路径 ─────────────────────────────────────────


def test_retry_dispatch_publish_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """celery_enabled=False 时把 ``_publish_execute_with_events`` 注册到 BackgroundTasks。"""
    from app.routers.dlq import _retry_dispatch
    from app.services.pipeline.tasks import _publish_execute_with_events

    _patch_settings(monkeypatch, celery_enabled=False)

    bg = BackgroundTasks()
    dispatcher = _retry_dispatch(
        _publish_dead(args_json=["plan-bg-1"], kwargs_json={"user_id": "u-bg"}),
        bg,
    )

    assert dispatcher == "background"
    assert len(bg.tasks) == 1
    task = bg.tasks[0]
    # 必须是真函数引用（不是 tick_task），位置参数顺序 (plan_id, user_id)
    assert task.func is _publish_execute_with_events
    assert task.args == ("plan-bg-1", "u-bg")


# ── 3. user_id fallback 到 dlq 行级 ────────────────────────────────────────


def test_retry_dispatch_publish_kwargs_user_id_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kwargs 没带 user_id 时 fallback 到 ``dead.user_id``（兼容旧 push 行）。"""
    from app.routers.dlq import _retry_dispatch
    from app.services.pipeline.tasks import _publish_execute_with_events

    _patch_settings(monkeypatch, celery_enabled=False)

    bg = BackgroundTasks()
    dispatcher = _retry_dispatch(
        _publish_dead(args_json=["plan-row-uid"], kwargs_json={}, user_id="u-row"),
        bg,
    )

    assert dispatcher == "background"
    assert bg.tasks[0].func is _publish_execute_with_events
    assert bg.tasks[0].args == ("plan-row-uid", "u-row")


# ── 4. 缺 plan_id 直接 400 ─────────────────────────────────────────────────


def test_retry_dispatch_publish_missing_plan_id_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """args 空 + kwargs 也无 plan_id → 抛 400，不偷偷成 retried。"""
    from app.routers.dlq import _retry_dispatch

    _patch_settings(monkeypatch, celery_enabled=False)

    bg = BackgroundTasks()
    with pytest.raises(HTTPException) as excinfo:
        _retry_dispatch(_publish_dead(args_json=[], kwargs_json={}), bg)
    assert excinfo.value.status_code == 400
    assert "plan_id" in str(excinfo.value.detail)
    assert bg.tasks == []


# ── 5. tick celery 路径回归 ────────────────────────────────────────────────


def test_retry_dispatch_tick_celery_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 publish 类（tick / execute_step）走原 tick_task.delay 不动。"""
    from app.routers.dlq import _retry_dispatch
    from app.services.pipeline import tasks as tasks_mod

    _patch_settings(monkeypatch, celery_enabled=True)

    captured: dict[str, Any] = {}

    def fake_delay(*args: Any, **kwargs: Any) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(tasks_mod.tick_task, "delay", fake_delay)

    bg = BackgroundTasks()
    dead = {
        "id": "dlq-tick-1",
        "task_name": "pipeline.tick",
        "args_json": ["run-123"],
        "kwargs_json": {},
        "run_id": "run-123",
        "user_id": "u-1",
        "status": "pending",
    }
    dispatcher = _retry_dispatch(dead, bg)

    assert dispatcher == "celery"
    assert captured["args"] == ("run-123",)
    assert bg.tasks == []


# ── 6. tick BackgroundTasks 路径回归 ───────────────────────────────────────


def test_retry_dispatch_tick_background_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 publish 类 + celery 关 → BackgroundTasks 收到 ``runner.tick``。"""
    from app.routers.dlq import _retry_dispatch
    from app.services.pipeline.runner import tick as runner_tick

    _patch_settings(monkeypatch, celery_enabled=False)

    bg = BackgroundTasks()
    dead = {
        "id": "dlq-tick-2",
        "task_name": "pipeline.execute_step",
        "args_json": ["step-x", "run-456"],
        "kwargs_json": {},
        "run_id": "run-456",
        "user_id": "u-2",
        "status": "pending",
    }
    dispatcher = _retry_dispatch(dead, bg)

    assert dispatcher == "background"
    assert len(bg.tasks) == 1
    assert bg.tasks[0].func is runner_tick
    assert bg.tasks[0].args == ("run-456",)


# ── 7. 非 publish 类 + 缺 run_id → 400 ─────────────────────────────────────


def test_retry_dispatch_tick_no_run_id_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """tick 类死信缺 run_id 时报错信息要带 task_name 方便排查。"""
    from app.routers.dlq import _retry_dispatch

    _patch_settings(monkeypatch, celery_enabled=False)

    bg = BackgroundTasks()
    dead = {
        "id": "dlq-broken",
        "task_name": "pipeline.tick",
        "args_json": [],
        "kwargs_json": {},
        "run_id": None,
        "user_id": "u-3",
        "status": "pending",
    }
    with pytest.raises(HTTPException) as excinfo:
        _retry_dispatch(dead, bg)
    assert excinfo.value.status_code == 400
    detail = str(excinfo.value.detail)
    assert "run_id" in detail
    assert "pipeline.tick" in detail
    assert bg.tasks == []
