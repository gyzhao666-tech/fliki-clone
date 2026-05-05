"""Track-14 admin · feature flags 路由测试。

覆盖
----
1. ``test_is_admin_email_default_demo``                    白名单 fallback：demo@example.com 命中
2. ``test_is_admin_email_env_overrides_default``           env ADMIN_EMAILS 完全覆盖（demo 失效）
3. ``test_admin_self_check_returns_role``                  /me 端点：admin / 非 admin 都 200，不抛 403
4. ``test_require_admin_rejects_non_admin``                _require_admin 非命中抛 HTTPException(403)
5. ``test_list_tenants_returns_grouped_summary``           /tenants 端点按 tenant_id 聚合 + flag_count
6. ``test_list_tenants_excludes_other_tenants_no_flag``    没设过 flag 的 tenant 不出现在 /tenants
7. ``test_admin_crud_round_trip``                          PUT → GET single → list → DELETE 全闭环

设计取舍
--------
- 路由 endpoint 是 ``async def``，但底层 ``_require_admin`` / ``_is_admin_email`` 是
  纯同步逻辑，可以直接函数级单测，避免起 TestClient + AsyncSession（Track-03 烟测
  里也踩过 sandbox event loop 跑 TestClient 失败的坑）。
- 用 SimpleNamespace 当 fake user，模拟 ``CurrentUser`` 的 ``email`` 属性，
  不引入真 ORM。
- DB 集成层只跑 ``feature_flags`` 表（Track-10 已迁过 head），
  不依赖任何用户/file/tenant_quotas 行；唯一副作用 = 自己写的 flag，teardown
  在每条 case 末尾显式 DELETE，跟 conftest 里的 ``test_t:`` 命名约定一致。
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from typing import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.unit  # 默认；个别 case 再覆盖标 integration


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_user(email: str) -> SimpleNamespace:
    """模拟 fastapi 注入的 ``current_user``；只用到 ``.email`` 字段。"""
    return SimpleNamespace(id="fake-uid", email=email, name="fake")


def _run(coro):
    """同步 case 里跑 async endpoint 函数。

    pytest-asyncio strict 模式下，标 ``unit`` 的 case 不应该自动 await；
    用 ``asyncio.run`` 一次性跑完。
    """
    return asyncio.run(coro)


@pytest.fixture
def admin_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """指定一个独立的 admin 邮箱，避免 demo fallback 与 case 顺序耦合。"""
    email = f"admin-{uuid.uuid4().hex[:6]}@pytest.local"
    monkeypatch.setenv("ADMIN_EMAILS", email)
    return email


@pytest.fixture
def temp_flag_tenant(pg_engine: Engine) -> Iterator[str]:
    """单 case 一个 tenant_id；teardown 删干净自己的 flag 行。

    用 ``test_t:`` 前缀（与 conftest 的 temp_tenant 同命名空间），
    确保不污染生产 ws:/u: tenant；同时让 /tenants 列表能稳定包含本 case。
    """
    tid = f"test_t:flag-{uuid.uuid4().hex[:8]}"
    yield tid
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM feature_flags WHERE tenant_id = :t"), {"t": tid}
        )


# ── 1. _is_admin_email / _allowed_admins ────────────────────────────────────


def test_is_admin_email_default_demo(monkeypatch: pytest.MonkeyPatch):
    """没配 ADMIN_EMAILS 时 demo@example.com fallback 命中（与 fixtures 一致）。"""
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    from app.routers import admin_flags as af

    assert af._is_admin_email("demo@example.com") is True
    assert af._is_admin_email("Demo@Example.com") is True  # 大小写不敏感
    assert af._is_admin_email("not-admin@example.com") is False
    assert af._is_admin_email(None) is False
    assert af._is_admin_email("") is False


def test_is_admin_email_env_overrides_default(monkeypatch: pytest.MonkeyPatch):
    """ADMIN_EMAILS 一旦配置，demo fallback 完全失效（不会同时命中）。"""
    monkeypatch.setenv("ADMIN_EMAILS", "alice@x.com, bob@y.com")
    from app.routers import admin_flags as af

    assert af._is_admin_email("alice@x.com") is True
    assert af._is_admin_email("bob@y.com") is True
    assert af._is_admin_email("BOB@y.com") is True
    assert af._is_admin_email("demo@example.com") is False  # fallback 被覆盖


# ── 2. /me 端点 ──────────────────────────────────────────────────────────────


def test_admin_self_check_returns_role(admin_env: str):
    """admin → is_admin=True；非 admin → is_admin=False；都不应 403（探测端点语义）。"""
    from app.routers.admin_flags import admin_self_check

    out_admin = _run(admin_self_check(_fake_user(admin_env)))
    assert out_admin.is_admin is True
    assert out_admin.email == admin_env

    out_random = _run(admin_self_check(_fake_user("random@x.com")))
    assert out_random.is_admin is False
    assert out_random.email == "random@x.com"


# ── 3. _require_admin gate ───────────────────────────────────────────────────


def test_require_admin_rejects_non_admin(admin_env: str):
    """非白名单调用必须 403；admin 调用不抛。"""
    from fastapi import HTTPException

    from app.routers.admin_flags import _require_admin

    _require_admin(_fake_user(admin_env))  # 不抛即 PASS

    with pytest.raises(HTTPException) as excinfo:
        _require_admin(_fake_user("intruder@x.com"))
    assert excinfo.value.status_code == 403


# ── 4. /tenants 列表 ────────────────────────────────────────────────────────


@pytest.mark.integration
def test_list_tenants_returns_grouped_summary(
    pg_engine: Engine, admin_env: str, temp_flag_tenant: str
):
    """/tenants 应聚合本 case 写入的 tenant；flag_count 与实写条数一致。"""
    from app.routers.admin_flags import list_tenants
    from app.services.pipeline import feature_flags as flag_service

    flag_service.set_flag(temp_flag_tenant, "art_ipadapter_pct", {"pct": 42})
    flag_service.set_flag(temp_flag_tenant, "voice_word_align_v4", {"enabled": True})

    out = _run(list_tenants(_fake_user(admin_env)))
    by_id = {t.tenant_id: t for t in out.tenants}
    assert temp_flag_tenant in by_id
    assert by_id[temp_flag_tenant].flag_count == 2
    # known_flags 字段透传：admin UI 顶部用作 hint
    assert "art_ipadapter_pct" in out.known_flags


@pytest.mark.integration
def test_list_tenants_excludes_tenant_without_flags(
    pg_engine: Engine, admin_env: str, temp_flag_tenant: str
):
    """从未写过 flag 的 tenant 不应出现在 /tenants（admin UI 顶部不刷垃圾选项）。"""
    from app.routers.admin_flags import list_tenants
    from app.services.pipeline import feature_flags as flag_service

    other_tid = f"test_t:noflag-{uuid.uuid4().hex[:6]}"
    flag_service.set_flag(temp_flag_tenant, "art_ipadapter_pct", {"pct": 10})

    out = _run(list_tenants(_fake_user(admin_env)))
    ids = {t.tenant_id for t in out.tenants}
    assert temp_flag_tenant in ids
    assert other_tid not in ids


# ── 5. CRUD 闭环 ─────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_admin_crud_round_trip(
    pg_engine: Engine, admin_env: str, temp_flag_tenant: str
):
    """PUT → GET single → list_flags → DELETE → GET 404 全链路；
    同时验证 admin 鉴权挂在每条端点上。
    """
    from fastapi import HTTPException

    from app.routers.admin_flags import (
        SetFlagBody,
        delete_flag,
        get_flag,
        list_flags,
        put_flag,
    )

    admin = _fake_user(admin_env)
    intruder = _fake_user("intruder@x.com")

    # 5.1 PUT 落库
    put_out = _run(
        put_flag(
            temp_flag_tenant,
            "art_ipadapter_pct",
            SetFlagBody(value={"pct": 50}),
            admin,
        )
    )
    assert put_out.value_json == {"pct": 50}

    # 5.2 GET single
    get_out = _run(get_flag(temp_flag_tenant, "art_ipadapter_pct", admin))
    assert get_out.value_json == {"pct": 50}

    # 5.3 list_flags
    list_out = _run(list_flags(admin, tenant_id=temp_flag_tenant))
    assert list_out.tenant_id == temp_flag_tenant
    assert list_out.flags.get("art_ipadapter_pct") == {"pct": 50}
    assert "art_ipadapter_pct" in list_out.known_flags

    # 5.4 鉴权：非 admin 调任意端点都 403
    for call in (
        lambda: _run(get_flag(temp_flag_tenant, "art_ipadapter_pct", intruder)),
        lambda: _run(list_flags(intruder, tenant_id=temp_flag_tenant)),
        lambda: _run(
            put_flag(
                temp_flag_tenant,
                "x",
                SetFlagBody(value={"pct": 1}),
                intruder,
            )
        ),
        lambda: _run(delete_flag(temp_flag_tenant, "art_ipadapter_pct", intruder)),
    ):
        with pytest.raises(HTTPException) as excinfo:
            call()
        assert excinfo.value.status_code == 403

    # 5.5 DELETE 应返回 deleted=True；二次 DELETE 返 deleted=False（幂等）
    del_out = _run(delete_flag(temp_flag_tenant, "art_ipadapter_pct", admin))
    assert del_out.deleted is True
    del_again = _run(delete_flag(temp_flag_tenant, "art_ipadapter_pct", admin))
    assert del_again.deleted is False

    # 5.6 GET single 404
    with pytest.raises(HTTPException) as excinfo:
        _run(get_flag(temp_flag_tenant, "art_ipadapter_pct", admin))
    assert excinfo.value.status_code == 404
