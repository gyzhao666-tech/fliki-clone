"""Track-30 · GET /api/team/workspaces/me 集成测试。

覆盖 6 case
-----------
1. ``test_owner_only_no_team_members_returns_admin``
   user 拥有 1 个 workspace，没有任何 team_members 行 → 返 1 条；role=admin；
   is_owner=True（owner-only fallback 路径）

2. ``test_owner_plus_membership_in_other_workspace_returns_two``
   user 拥有 1 个 workspace + 在另 1 workspace 是 team_member（role=editor） →
   返 2 条；own 那条 role=admin / is_owner=True；member 那条 role=editor /
   is_owner=False；created_at ASC 排序

3. ``test_role_comes_from_team_members_when_owner_also_member``
   user 是 workspace 的 owner，**同时**在 team_members 里 role=viewer → 应返 1 条
   role=viewer（team_members "后者优先"）；is_owner=True 仍正确反映 owner 关系

4. ``test_empty_user_returns_zero_workspaces``
   全新用户，无 own 也无 team_members 行 → 返 ``{"workspaces": []}``，HTTP 200

5. ``test_unauthenticated_returns_401``
   ``get_current_user(token=None)`` 不带 cookie / Authorization 头 → 抛 401。
   覆盖既有 fixture 行为（路由用 ``CurrentUser`` 依赖 → 鉴权层先于业务层执行）

6. ``test_invited_pending_member_with_user_id_appears_in_list``
   member.status=pending（invite 已发但未 accept）但 user_id 已绑定 → 仍出现在
   列表里（避免 v1 邀请流程把 active vs pending 混淆；实际语义由 sidebar 自己处理）

设计取舍
--------
- 路由是 ``async def``：用 ``@pytest.mark.asyncio`` 让 pytest-asyncio 接管 event loop，
  避免每个 case 自起 ``asyncio.new_event_loop()`` 与全局 ``AsyncSessionLocal``
  连接池跨 loop 引发 ``Future attached to a different loop``。
- ``temp_user`` fixture（conftest）已建好用户行；本文件提供 ``_make_workspace``
  / ``_make_team_member`` helper 手工拼场景，避免污染 conftest（与 test_track24_rbac
  helper 同款）。
- 走真 PG（``pytest.mark.integration``）；teardown 清 team_members + workspaces
  顺序避免外键报错。
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_user(*, user_id: str, email: str) -> SimpleNamespace:
    """模拟 fastapi 注入的 ``current_user``；只用到 .id / .email / .name。"""
    return SimpleNamespace(id=user_id, email=email, name="pytest user")


def _make_workspace(engine: Engine, owner_id: str, name: str = "pytest ws") -> str:
    wid = f"test_ws30_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO workspaces (id, owner_id, name, created_at)
                VALUES (:id, :ow, :nm, NOW())
                """
            ),
            {"id": wid, "ow": owner_id, "nm": name},
        )
    return wid


def _make_team_member(
    engine: Engine,
    *,
    workspace_id: str,
    user_id: str,
    email: str,
    role: str = "editor",
    status: str = "active",
) -> str:
    tmid = f"test_tm30_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO team_members (id, workspace_id, user_id, email, role, status, created_at)
                VALUES (:id, :w, :u, :em, :r, :st, NOW())
                """
            ),
            {
                "id": tmid,
                "w": workspace_id,
                "u": user_id,
                "em": email,
                "r": role,
                "st": status,
            },
        )
    return tmid


def _cleanup_workspace(engine: Engine, workspace_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM team_members WHERE workspace_id = :w"),
            {"w": workspace_id},
        )
        conn.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace_id})


@pytest.fixture
def t30_workspace(
    pg_engine: Engine, temp_user: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """temp_user + 自建 1 个 workspace（owner=temp_user）+ teardown 清理。"""
    wid = _make_workspace(pg_engine, owner_id=temp_user["id"])
    yield {"workspace_id": wid, "owner": temp_user}
    _cleanup_workspace(pg_engine, wid)


# ── Route caller ─────────────────────────────────────────────────────────────


async def _call_list_my_workspaces(user: SimpleNamespace) -> Any:
    """把 ``list_my_workspaces`` 包成「拿 AsyncSession + 调 route」一次性调用。

    每个 case 创建一个独立 ``create_async_engine`` 引擎并在 case 末尾 dispose，
    避免 ``app.database.engine`` 模块级单例的连接池被跨测试 event loop 复用导致
    ``Future attached to a different loop``（pytest-asyncio strict mode 默认每个
    test 起独立 loop；engine 在 import time 已 bind 到第一个 case 的 loop）。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.routers.team import list_my_workspaces

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            return await list_my_workspaces(current_user=user, db=db)
    finally:
        await engine.dispose()


# ── 1. owner-only 无 team_members 行 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_only_no_team_members_returns_admin(
    pg_engine: Engine, t30_workspace: dict[str, Any]
):
    """user own 1 workspace，没在 team_members 落行 → 返 1 条 role=admin。"""
    owner = t30_workspace["owner"]
    wid = t30_workspace["workspace_id"]

    user = _fake_user(user_id=owner["id"], email=owner["email"])
    out = await _call_list_my_workspaces(user)

    assert len(out.workspaces) == 1
    item = out.workspaces[0]
    assert item.id == wid
    assert item.role == "admin"
    assert item.is_owner is True


# ── 2. owner + 另 workspace 的 team_member ──────────────────────────────────


@pytest.mark.asyncio
async def test_owner_plus_membership_in_other_workspace_returns_two(
    pg_engine: Engine, t30_workspace: dict[str, Any]
):
    """user own 1 个 + 是另 1 个的 team_member → 应返 2 条。"""
    owner = t30_workspace["owner"]
    own_wid = t30_workspace["workspace_id"]

    other_owner_id = f"test_u_{uuid.uuid4().hex[:10]}"
    other_owner_email = f"{other_owner_id}@pytest.local"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, name, hashed_password, plan,
                    credits_used, credits_total, email_notifications,
                    youtube_channel_ids, created_at, updated_at)
                VALUES (:id, :em, 'pt', '!', 'free', 0, 0, false,
                    '{}', NOW(), NOW())
                """
            ),
            {"id": other_owner_id, "em": other_owner_email},
        )
    other_wid = _make_workspace(
        pg_engine, owner_id=other_owner_id, name="other-team-ws"
    )
    _make_team_member(
        pg_engine,
        workspace_id=other_wid,
        user_id=owner["id"],
        email=owner["email"],
        role="editor",
        status="active",
    )

    try:
        user = _fake_user(user_id=owner["id"], email=owner["email"])
        out = await _call_list_my_workspaces(user)

        assert len(out.workspaces) == 2
        by_id = {w.id: w for w in out.workspaces}

        own_item = by_id[own_wid]
        assert own_item.role == "admin"
        assert own_item.is_owner is True

        member_item = by_id[other_wid]
        assert member_item.role == "editor"
        assert member_item.is_owner is False

        assert out.workspaces[0].id == own_wid
        assert out.workspaces[1].id == other_wid
    finally:
        _cleanup_workspace(pg_engine, other_wid)
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM users WHERE id = :u"), {"u": other_owner_id}
            )


# ── 3. role 来自 team_members（非 owner 兜底） ──────────────────────────────


@pytest.mark.asyncio
async def test_role_comes_from_team_members_when_owner_also_member(
    pg_engine: Engine, t30_workspace: dict[str, Any]
):
    """user 是 workspace owner + team_members.role=viewer → 取 team_members 的
    viewer，不能因 owner 兜底成 admin（spec：「后者优先」与 PATCH 降级语义一致）。"""
    owner = t30_workspace["owner"]
    wid = t30_workspace["workspace_id"]

    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner["id"],
        email=owner["email"],
        role="viewer",
        status="active",
    )

    user = _fake_user(user_id=owner["id"], email=owner["email"])
    out = await _call_list_my_workspaces(user)

    assert len(out.workspaces) == 1
    item = out.workspaces[0]
    assert item.id == wid
    assert item.role == "viewer", "team_members 行存在时其 role 优先于 owner 兜底"
    assert item.is_owner is True, "is_owner 仍反映真 owner 关系（与 role 解耦）"


# ── 4. empty user ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_user_returns_zero_workspaces(
    pg_engine: Engine, temp_user: dict[str, Any]
):
    """user 没 own / 没 team_members 行 → 返 ``{"workspaces": []}``，不抛 404。"""
    user = _fake_user(user_id=temp_user["id"], email=temp_user["email"])
    out = await _call_list_my_workspaces(user)

    assert out.workspaces == []


# ── 5. 未登录 → 401 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_returns_401():
    """``get_current_user`` 没拿到 cookie / Authorization 头时抛 401。

    本路由用 ``CurrentUser = Annotated[User, Depends(get_current_user)]``，
    fastapi 在调路由前先解依赖；依赖抛 401 → 整个 GET /workspaces/me 直接 401，
    不会进 ``list_my_workspaces`` 函数体。本 case 直接证实底层依赖行为，
    避开 sandbox event loop 起 TestClient 的坑（参考 test_admin_flags 注释）。
    """
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.deps import get_current_user

    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            with pytest.raises(HTTPException) as excinfo:
                await get_current_user(db=db, token=None, authorization=None)
        assert excinfo.value.status_code == 401
    finally:
        await engine.dispose()


# ── 6. invite pending 但 user_id 已绑 → 仍可见 ──────────────────────────────


@pytest.mark.asyncio
async def test_invited_pending_member_with_user_id_appears_in_list(
    pg_engine: Engine, t30_workspace: dict[str, Any]
):
    """member.status=pending（user 邀请进来但还没 accept invite）但 user_id 已绑定
    时，应仍出现在 workspaces/me 里：v1 接邀流程不强制区分 active vs pending，
    避免登录后 sidebar 突然空 dropdown。
    """
    owner = t30_workspace["owner"]
    own_wid = t30_workspace["workspace_id"]

    other_owner_id = f"test_u_{uuid.uuid4().hex[:10]}"
    other_owner_email = f"{other_owner_id}@pytest.local"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, name, hashed_password, plan,
                    credits_used, credits_total, email_notifications,
                    youtube_channel_ids, created_at, updated_at)
                VALUES (:id, :em, 'pt', '!', 'free', 0, 0, false,
                    '{}', NOW(), NOW())
                """
            ),
            {"id": other_owner_id, "em": other_owner_email},
        )
    other_wid = _make_workspace(pg_engine, owner_id=other_owner_id)
    _make_team_member(
        pg_engine,
        workspace_id=other_wid,
        user_id=owner["id"],
        email=owner["email"],
        role="viewer",
        status="pending",
    )

    try:
        user = _fake_user(user_id=owner["id"], email=owner["email"])
        out = await _call_list_my_workspaces(user)

        ids = {w.id for w in out.workspaces}
        assert own_wid in ids
        assert other_wid in ids, "pending member 也应可见，避免 sidebar 空 dropdown"
        member_item = next(w for w in out.workspaces if w.id == other_wid)
        assert member_item.role == "viewer"
        assert member_item.is_owner is False
    finally:
        _cleanup_workspace(pg_engine, other_wid)
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM users WHERE id = :u"), {"u": other_owner_id}
            )
