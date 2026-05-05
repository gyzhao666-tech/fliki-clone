"""Track-24 · RBAC v1 测试（workspace member role）。

覆盖（10 case）
---------------
1. ``test_alembic_role_column_default_and_index``      schema 状态：role 列 server_default + 索引
2. ``test_team_member_default_role_editor``            INSERT 不指定 role 时落 'editor'（server default 生效）
3. ``test_workspace_owner_backfilled_admin``           backfill 语义：owner 一定是 admin
4. ``test_get_user_role_three_states``                 admin / editor / 不在 workspace 三状态
5. ``test_is_admin_email_fallback_when_no_membership`` user 没有 team_members → 邮箱白名单兜底
6. ``test_is_admin_via_team_member_explicit_workspace`` 显式 workspace_id → role=admin 命中
7. ``test_is_admin_via_team_member_any_workspace``     workspace_id 缺省 → 遍历用户 admin 命中
8. ``test_is_admin_cache_ttl_behavior``                改 DB 不立刻反映；clear_cache 后立刻反映
9. ``test_require_admin_integration_admin_email``      _require_admin：邮箱白名单通过
10. ``test_require_admin_integration_team_member``     _require_admin：team_member.role=admin 通过

设计取舍
--------
- 大多数 case 走真 PG（``team_members`` / ``workspaces`` / ``users`` 三张表），
  靠 ``temp_user`` + 自建 workspace + team_members 行 + teardown 删干净
- 单元 case 仅 1（``test_is_admin_email_fallback_when_no_membership``）：用
  inexistent user_id 触发「DB 路径都没命中 → fallback 邮箱白名单」
- ``rbac.clear_cache()`` 在每个用 cache 的 case 起头都调，避免 case 顺序耦合
- conftest 的 ``temp_user`` 不会自动建 workspace / team_member；本文件提供
  ``_workspace`` / ``_team_member`` 两个轻量 helper，case 自己拼装
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration  # 大部分 case 走真 PG


# ── helpers ──────────────────────────────────────────────────────────────────


def _fake_user(*, user_id: str, email: str) -> SimpleNamespace:
    """模拟 fastapi 注入的 ``current_user``；只用到 .id / .email。"""
    return SimpleNamespace(id=user_id, email=email, name="pytest user")


def _run(coro):
    return asyncio.run(coro)


def _make_workspace(engine: Engine, owner_id: str, name: str = "pytest ws") -> str:
    """建一个 workspace 行，返回 id；不写 team_members。"""
    wid = f"test_ws_{uuid.uuid4().hex[:10]}"
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
    role: str | None = None,
    status: str = "active",
) -> str:
    """建一个 team_members 行；role=None 时不传，看 server_default 是否生效。"""
    tmid = f"test_tm_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        if role is None:
            conn.execute(
                text(
                    """
                    INSERT INTO team_members (id, workspace_id, user_id, email, status, created_at)
                    VALUES (:id, :w, :u, :em, :st, NOW())
                    """
                ),
                {"id": tmid, "w": workspace_id, "u": user_id, "em": email, "st": status},
            )
        else:
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


@pytest.fixture
def workspace_with_owner(
    pg_engine: Engine, temp_user: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """temp_user + 自建 workspace（owner=temp_user）+ teardown 清理。

    不自动写 team_members（让 case 自己控制 owner 是否登记 + 别的 user 角色）。
    """
    wid = _make_workspace(pg_engine, owner_id=temp_user["id"])
    yield {"workspace_id": wid, "owner": temp_user}
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM team_members WHERE workspace_id = :w"), {"w": wid})
        conn.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": wid})


@pytest.fixture
def admin_email_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """指定一个独立的 admin 邮箱并清掉 settings cache + rbac cache。"""
    from app.config import get_settings
    from app.services.auth import rbac

    email = f"admin-{uuid.uuid4().hex[:6]}@pytest.local"
    monkeypatch.setenv("ADMIN_EMAILS", email)
    get_settings.cache_clear()
    rbac.clear_cache()
    yield email
    get_settings.cache_clear()
    rbac.clear_cache()


# ── 1. alembic schema 状态 ──────────────────────────────────────────────────


def test_alembic_role_column_default_and_index(pg_engine: Engine):
    """team_members.role 应有 VARCHAR(20) + server_default 'editor' + ix_team_members_role 索引。"""
    insp = inspect(pg_engine)
    cols = {c["name"]: c for c in insp.get_columns("team_members")}
    assert "role" in cols, "role column missing on team_members"
    role_col = cols["role"]
    assert role_col["nullable"] is False
    # PG 把 server_default 渲染成 "'editor'::character varying" 形态
    default_repr = str(role_col.get("default") or "")
    assert "editor" in default_repr.lower(), f"unexpected default: {default_repr!r}"

    indexes = {i["name"]: i for i in insp.get_indexes("team_members")}
    assert "ix_team_members_role" in indexes, "ix_team_members_role index missing"
    assert indexes["ix_team_members_role"]["column_names"] == ["role"]


# ── 2. server default 生效 ──────────────────────────────────────────────────


def test_team_member_default_role_editor(
    pg_engine: Engine, workspace_with_owner: dict[str, Any]
):
    """INSERT 不显式指定 role → DB 落 'editor'（server_default 生效）。

    覆盖 ORM Python-side default 之外的另一条路径：直接 SQL 插入。
    """
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    # 建一个不是 owner 的 fake user 行 + team_member（role 不传）
    other_uid = f"test_u_{uuid.uuid4().hex[:10]}"
    other_email = f"{other_uid}@pytest.local"
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
            {"id": other_uid, "em": other_email},
        )
    try:
        tmid = _make_team_member(
            pg_engine,
            workspace_id=wid,
            user_id=other_uid,
            email=other_email,
            role=None,  # 走 server default
        )
        with pg_engine.connect() as conn:
            row = conn.execute(
                text("SELECT role FROM team_members WHERE id = :id"), {"id": tmid}
            ).fetchone()
        assert row is not None
        assert row[0] == "editor"
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM team_members WHERE user_id = :u"), {"u": other_uid})
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_uid})


# ── 3. backfill：owner → admin ──────────────────────────────────────────────


def test_workspace_owner_backfilled_admin(
    pg_engine: Engine, workspace_with_owner: dict[str, Any]
):
    """新建一个 team_member(owner=user_id, role='editor') 后手动跑 backfill SQL。

    backfill 脚本本身只在 alembic upgrade 时跑一次，不能假设当前环境必有 owner
    的 team_member 行。本 case 模拟「先以 editor 落库，再跑 backfill SQL，
    应被改成 admin」，覆盖 backfill 的核心 UPDATE 语义。
    """
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    tmid = _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="editor",
    )
    # 跑 backfill 语义（与 alembic upgrade 里同款 SQL）
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE team_members tm
                   SET role = 'admin'
                  FROM workspaces w
                 WHERE tm.workspace_id = w.id
                   AND tm.user_id = w.owner_id
                   AND tm.role <> 'admin'
                """
            )
        )
        row = conn.execute(
            text("SELECT role FROM team_members WHERE id = :id"), {"id": tmid}
        ).fetchone()
    assert row is not None and row[0] == "admin"


# ── 4. get_user_role 三状态 ──────────────────────────────────────────────────


def test_get_user_role_three_states(
    pg_engine: Engine, workspace_with_owner: dict[str, Any]
):
    """覆盖 admin / editor / 不在 workspace 三状态。"""
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    # 4.1 不在 workspace → None
    assert rbac.get_user_role("totally-random-uid", wid) is None

    # 4.2 owner 登记为 admin → 'admin'
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="admin",
    )
    rbac.clear_cache()
    assert rbac.get_user_role(owner_id, wid) == "admin"

    # 4.3 另起 user 登记为 editor → 'editor'
    other_uid = f"test_u_{uuid.uuid4().hex[:10]}"
    other_email = f"{other_uid}@pytest.local"
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
            {"id": other_uid, "em": other_email},
        )
    try:
        _make_team_member(
            pg_engine,
            workspace_id=wid,
            user_id=other_uid,
            email=other_email,
            role="editor",
        )
        rbac.clear_cache()
        assert rbac.get_user_role(other_uid, wid) == "editor"
    finally:
        with pg_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM team_members WHERE user_id = :u"), {"u": other_uid}
            )
            conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": other_uid})


# ── 5. is_admin 邮箱兜底（无 team_member 命中） ─────────────────────────────


def test_is_admin_email_fallback_when_no_membership(admin_email_env: str):
    """user 没有任何 team_members.role==admin 行 → 走 _is_admin_email fallback。

    使用一个绝对不存在的 user_id 让 DB 路径全部 miss；email 命中白名单 → True。
    使用 inexistent user_id + email 不命中 → False。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    fake_uid = f"nonexistent-{uuid.uuid4().hex}"

    # 5.1 邮箱命中白名单 → True
    assert rbac.is_admin(fake_uid, email=admin_email_env) is True

    # 5.2 邮箱没命中 → False
    assert rbac.is_admin(fake_uid, email="not-admin@x.com") is False

    # 5.3 user_id 也缺 → 仅看 email
    assert rbac.is_admin(None, email=admin_email_env) is True
    assert rbac.is_admin(None, email=None) is False


# ── 6. is_admin via team_member 显式 workspace ─────────────────────────────


def test_is_admin_via_team_member_explicit_workspace(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """显式 workspace_id 命中：role==admin → True；role==editor → fallback 邮箱（不命中也 False）。"""
    from app.config import get_settings
    from app.services.auth import rbac

    monkeypatch.setenv("ADMIN_EMAILS", "")  # 故意把白名单清空，避免 fallback 干扰
    get_settings.cache_clear()
    rbac.clear_cache()

    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    # role=admin → True
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="admin",
    )
    rbac.clear_cache()
    assert (
        rbac.is_admin(owner_id, workspace_id=wid, email="totally-random@x.com") is True
    )

    # 删掉再以 editor 落 → False（路径 1 不命中 + 路径 3 邮箱白名单空 → 只有 demo fallback）
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM team_members WHERE workspace_id=:w"), {"w": wid})
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="editor",
    )
    rbac.clear_cache()
    # owner_email 不是 demo@example.com（fixture 给的是 test_u_...@pytest.local），
    # ADMIN_EMAILS 空 → fallback 走 demo@example.com 默认；不命中 → False
    assert (
        rbac.is_admin(owner_id, workspace_id=wid, email=owner_email) is False
    )

    get_settings.cache_clear()


# ── 7. is_admin via team_member workspace_id 缺省（遍历） ────────────────────


def test_is_admin_via_team_member_any_workspace(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """workspace_id 缺省 → 遍历用户所有 workspace，任意 admin 即命中。"""
    from app.config import get_settings
    from app.services.auth import rbac

    monkeypatch.setenv("ADMIN_EMAILS", "")
    get_settings.cache_clear()
    rbac.clear_cache()

    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]
    wid = workspace_with_owner["workspace_id"]
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="admin",
    )

    # 不传 workspace_id，靠遍历命中
    rbac.clear_cache()
    assert rbac.is_admin(owner_id, email="totally-random@x.com") is True

    get_settings.cache_clear()


# ── 8. cache TTL 行为 ───────────────────────────────────────────────────────


def test_is_admin_cache_ttl_behavior(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    """首次查询命中后写入缓存；DB 改变不立刻反映；clear_cache 后立刻反映。

    只验证 cache 行为；不强制 60s 真实 sleep（CI 跑不起）。
    """
    from app.config import get_settings
    from app.services.auth import rbac

    monkeypatch.setenv("ADMIN_EMAILS", "")
    get_settings.cache_clear()
    rbac.clear_cache()

    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]
    wid = workspace_with_owner["workspace_id"]
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="admin",
    )

    # 8.1 首次查询写缓存
    assert rbac.get_user_role(owner_id, wid) == "admin"

    # 8.2 直接改 DB role 为 editor，但缓存未失效 → 仍返 admin
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE team_members SET role='editor' WHERE workspace_id=:w AND user_id=:u"
            ),
            {"w": wid, "u": owner_id},
        )
    assert rbac.get_user_role(owner_id, wid) == "admin", "cache should still hold"

    # 8.3 clear_cache 后立刻反映新 DB 状态
    rbac.clear_cache()
    assert rbac.get_user_role(owner_id, wid) == "editor"

    get_settings.cache_clear()


# ── 9. _require_admin 集成：admin 邮箱兜底通过 ───────────────────────────────


def test_require_admin_integration_admin_email(admin_email_env: str):
    """admin 邮箱命中 → _require_admin 不抛；非 admin 邮箱抛 403（兼容老语义）。"""
    from fastapi import HTTPException

    from app.routers.admin_flags import _require_admin
    from app.services.auth import rbac

    rbac.clear_cache()
    # 用一个绝不会有 team_members 行的 user_id，强制走邮箱 fallback
    admin_user = _fake_user(user_id=f"nonexistent-{uuid.uuid4().hex}", email=admin_email_env)
    _require_admin(admin_user)  # 不抛即 PASS

    intruder = _fake_user(
        user_id=f"nonexistent-{uuid.uuid4().hex}", email="intruder@x.com"
    )
    with pytest.raises(HTTPException) as excinfo:
        _require_admin(intruder)
    assert excinfo.value.status_code == 403


# ── 10. _require_admin 集成：team_member.role=admin 通过 ─────────────────────


def test_require_admin_integration_team_member(
    pg_engine: Engine,
    workspace_with_owner: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """team_member.role=admin → _require_admin 不抛（即使邮箱不在白名单）。

    覆盖 Track-24 引入的「admin 主路径」：邮箱不命中也能因为 role=admin 通过。
    """
    from app.config import get_settings
    from app.routers.admin_flags import _require_admin
    from app.services.auth import rbac

    monkeypatch.setenv("ADMIN_EMAILS", "noone@nowhere.local")  # 故意把白名单设成不命中
    get_settings.cache_clear()
    rbac.clear_cache()

    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]
    wid = workspace_with_owner["workspace_id"]
    _make_team_member(
        pg_engine,
        workspace_id=wid,
        user_id=owner_id,
        email=owner_email,
        role="admin",
    )
    rbac.clear_cache()

    # 邮箱不在白名单 + 但 team_member.role=admin → 通过
    user = _fake_user(user_id=owner_id, email=owner_email)
    _require_admin(user)  # 不抛即 PASS

    get_settings.cache_clear()
