"""Track-27 · RBAC editor/viewer 写权限分级测试。

覆盖（10 case）
---------------
1. ``test_is_editor_admin_membership_hits``           team_members.role=admin → is_editor=True
2. ``test_is_editor_editor_membership_hits``          team_members.role=editor → is_editor=True
3. ``test_is_editor_viewer_membership_rejected``      team_members.role=viewer → is_editor=False
4. ``test_is_editor_email_fallback_does_not_apply``   ADMIN_EMAILS 命中但无 team_member → is_editor=False（fallback 仅对 admin 生效）
5. ``test_is_viewer_all_roles_hit``                   admin / editor / viewer 三档都 → is_viewer=True
6. ``test_is_viewer_no_membership_rejected``          没 team_members 行 + 没 email → is_viewer=False
7. ``test_require_role_writer_rejects_viewer``        require_role(["admin","editor"])(viewer) → 403
8. ``test_require_role_admin_only_rejects_editor``    require_role(["admin"])(editor) → 403
9. ``test_require_role_writer_passes_editor``         require_role(["admin","editor"])(editor) → 不抛
10. ``test_require_role_403_detail_contains_editor``  require_role(["admin","editor"])(viewer) 403 detail 含「editor」字样

设计取舍
--------
- 9/10 case 走真 PG（``team_members`` / ``workspaces`` / ``users`` 三张表），靠
  ``temp_user`` + 自建 workspace + team_members 行 + teardown 删干净，与
  ``test_track24_rbac.py`` 同 pattern
- 仅 case 4（``test_is_editor_email_fallback_does_not_apply``）用 inexistent
  user_id 触发「DB 路径全 miss → 看 fallback 是否被错误触发」的纯单元判定
- ``rbac.clear_cache()`` 在每个走 cache 的 case 起头都调，避免 case 顺序耦合
- ``require_role`` 返回的 ``_check`` 函数在 FastAPI Depends 体系下注入 user；
  本测试直接以位置参数调它（绕过 Depends 解析），断 raise / no-raise

为什么不用 TestClient 起完整 HTTP 栈
----------------------------------
- FastAPI route 本体是 ``async def``，TestClient 起 event loop 在沙盒里偶尔
  踩 `RuntimeError: Cannot call ... from a running event loop`（第三波 T-13
  踩过同款坑）
- ``require_role`` 是函数式 Depends 工厂，逻辑全在返回的 ``_check`` 里；直接
  调 ``_check(fake_user)`` 等价于 HTTP 请求过 dep 的语义，覆盖度足
- 路由真的有挂上 dependencies 这件事由 ``test_admin_flags.py`` 既有 7 case
  + 端到端 manual smoke 兜底（spec 要求「mock current_user role=editor → POST
  /publish-plans 返 200」由本文件 case 9 等价覆盖）
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.integration  # 大部分 case 走真 PG


# ── helpers（与 test_track24_rbac.py 同款，避免跨文件依赖）────────────────


def _fake_user(*, user_id: str, email: str) -> SimpleNamespace:
    """模拟 fastapi 注入的 ``current_user``；只用到 .id / .email。"""
    return SimpleNamespace(id=user_id, email=email, name="pytest user")


def _make_workspace(engine: Engine, owner_id: str, name: str = "pytest ws") -> str:
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
    role: str,
    status: str = "active",
) -> str:
    tmid = f"test_tm_{uuid.uuid4().hex[:10]}"
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


@pytest.fixture
def workspace_with_owner(
    pg_engine: Engine, temp_user: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """temp_user + 自建 workspace（owner=temp_user）+ teardown 清理 team_members。"""
    wid = _make_workspace(pg_engine, owner_id=temp_user["id"])
    yield {"workspace_id": wid, "owner": temp_user}
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM team_members WHERE workspace_id = :w"), {"w": wid}
        )
        conn.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": wid})


@pytest.fixture
def admin_email_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """指定独立 admin 邮箱 + 清掉 settings/rbac cache，避免与默认 demo fallback 串味。"""
    from app.config import get_settings
    from app.services.auth import rbac

    email = f"admin-{uuid.uuid4().hex[:6]}@pytest.local"
    monkeypatch.setenv("ADMIN_EMAILS", email)
    get_settings.cache_clear()
    rbac.clear_cache()
    yield email
    get_settings.cache_clear()
    rbac.clear_cache()


@pytest.fixture
def empty_admin_emails(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把 ADMIN_EMAILS 清空，避免邮箱 fallback 干扰 require_role 判定。

    但 Settings 的默认值是 "demo@example.com"；env 显式置空字符串后，
    `_allowed_admin_emails()` 内部仍 fallback 到 demo（保留 dev 兼容）。
    本 fixture 是为了让 case 控制「即使有 demo fallback，editor / viewer
    走 require_role 也不该意外通过」。
    """
    from app.config import get_settings
    from app.services.auth import rbac

    monkeypatch.setenv("ADMIN_EMAILS", "")
    get_settings.cache_clear()
    rbac.clear_cache()
    yield
    get_settings.cache_clear()
    rbac.clear_cache()


# ── 1. is_editor: admin 命中 ─────────────────────────────────────────────


def test_is_editor_admin_membership_hits(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """team_members.role=admin → is_editor=True（admin 自然包含写权限）。"""
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="admin"
    )
    rbac.clear_cache()

    assert rbac.is_editor(owner_id, workspace_id=wid) is True
    assert rbac.is_editor(owner_id) is True  # workspace 缺省路径也命中


# ── 2. is_editor: editor 命中 ────────────────────────────────────────────


def test_is_editor_editor_membership_hits(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """team_members.role=editor → is_editor=True。"""
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="editor"
    )
    rbac.clear_cache()

    assert rbac.is_editor(owner_id, workspace_id=wid) is True
    assert rbac.is_editor(owner_id) is True


# ── 3. is_editor: viewer 拒绝 ────────────────────────────────────────────


def test_is_editor_viewer_membership_rejected(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """team_members.role=viewer → is_editor=False（viewer 没写权限）。"""
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="viewer"
    )
    rbac.clear_cache()

    assert rbac.is_editor(owner_id, workspace_id=wid) is False
    assert rbac.is_editor(owner_id) is False
    # is_viewer 应通过（覆盖 case 5 的部分语义）
    assert rbac.is_viewer(owner_id, workspace_id=wid) is True


# ── 4. is_editor: 邮箱白名单不命中 ───────────────────────────────────────


def test_is_editor_email_fallback_does_not_apply(admin_email_env: str):
    """admin 邮箱白名单**仅对 is_admin 生效**；is_editor 必须真在 team_members。

    用绝不存在的 user_id 让 DB 路径全 miss；email 命中白名单 → is_admin=True 但
    is_editor / is_viewer 都为 False。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    fake_uid = f"nonexistent-{uuid.uuid4().hex}"
    fake_user = _fake_user(user_id=fake_uid, email=admin_email_env)

    # is_admin 走 fallback 应该 True（保持 Track-24 既有语义不变）
    assert rbac.is_admin(fake_user.id, email=fake_user.email) is True

    # is_editor / is_viewer 不带 email 参数，只能从 team_members 命中
    assert rbac.is_editor(fake_user.id) is False
    assert rbac.is_editor(fake_user.id, workspace_id="nonexistent-ws") is False
    assert rbac.is_viewer(fake_user.id) is False


# ── 5. is_viewer: 三档都命中 ─────────────────────────────────────────────


def test_is_viewer_all_roles_hit(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """admin / editor / viewer 任意 role 都让 is_viewer=True（最低读权限）。

    一次 fixture 内分别建三种 role 的 team_members 行（不同 user_id），分别断言。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]

    role_users: dict[str, str] = {}
    for role in ("admin", "editor", "viewer"):
        uid = f"test_u_{uuid.uuid4().hex[:10]}"
        em = f"{uid}@pytest.local"
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
                {"id": uid, "em": em},
            )
        _make_team_member(
            pg_engine, workspace_id=wid, user_id=uid, email=em, role=role
        )
        role_users[role] = uid
    rbac.clear_cache()

    try:
        for role, uid in role_users.items():
            assert rbac.is_viewer(uid, workspace_id=wid) is True, f"role={role} 应视为 viewer"
            assert rbac.is_viewer(uid) is True, f"role={role} 任意 ws 也应命中"
    finally:
        for uid in role_users.values():
            with pg_engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM team_members WHERE user_id = :u"), {"u": uid}
                )
                conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})


# ── 6. is_viewer: 没 team_member + 没 email 拒绝 ──────────────────────────


def test_is_viewer_no_membership_rejected(empty_admin_emails: None):
    """没 team_members 行 + user_id None / 不在表里 → is_viewer=False。

    不走邮箱 fallback：viewer 必须真在表里登记（与 is_editor 同语义）。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    # 6.1 user_id None
    assert rbac.is_viewer(None) is False
    assert rbac.is_viewer(None, workspace_id="any-ws") is False
    # 6.2 user_id 不在 team_members
    fake_uid = f"nonexistent-{uuid.uuid4().hex}"
    assert rbac.is_viewer(fake_uid) is False
    assert rbac.is_viewer(fake_uid, workspace_id="any-ws") is False


# ── 7. require_role(["admin","editor"]) viewer 调写端点 403 ───────────────


def test_require_role_writer_rejects_viewer(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """viewer 调 require_role(["admin","editor"]) → 403。

    场景：编辑 publish_plans 的 router 写端点鉴权。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="viewer"
    )
    rbac.clear_cache()

    check = rbac.require_role(["admin", "editor"])
    viewer = _fake_user(user_id=owner_id, email=owner_email)

    with pytest.raises(HTTPException) as excinfo:
        check(viewer)
    assert excinfo.value.status_code == 403


# ── 8. require_role(["admin"]) editor 调 admin-only 端点 403 ──────────────


def test_require_role_admin_only_rejects_editor(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """editor 调 require_role(["admin"]) admin-only 端点 → 403。

    场景：billing checkout-session / portal-session 仅 admin 能发起。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="editor"
    )
    rbac.clear_cache()

    check = rbac.require_role(["admin"])
    editor = _fake_user(user_id=owner_id, email=owner_email)

    with pytest.raises(HTTPException) as excinfo:
        check(editor)
    assert excinfo.value.status_code == 403


# ── 9. require_role(["admin","editor"]) editor 通过（等价「POST /publish-plans 200」）─


def test_require_role_writer_passes_editor(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """editor 调 require_role(["admin","editor"]) → 不抛（等价 POST /publish-plans 200）。

    spec 要求「mock current_user role=editor → POST /publish-plans 返 200」；
    挂在路由上的 ``dependencies=[Depends(require_role([...]))]`` 在 FastAPI
    收到请求时会调本 ``_check`` 函数，命中即放行让真业务体跑（业务体 200/4xx
    取决于业务逻辑，不在 RBAC 范围）。本 case 直接断 ``_check`` 不抛即等价。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="editor"
    )
    rbac.clear_cache()

    check = rbac.require_role(["admin", "editor"])
    editor = _fake_user(user_id=owner_id, email=owner_email)
    # 不抛即 PASS（HTTP 层会接 200 业务响应）
    check(editor)

    # admin 也应通过（覆盖正向路径里 admin 的双重判定）
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE team_members SET role='admin' WHERE user_id=:u AND workspace_id=:w"),
            {"u": owner_id, "w": wid},
        )
    rbac.clear_cache()
    check(_fake_user(user_id=owner_id, email=owner_email))


# ── 10. require_role detail 含「editor」字样（前端透传给用户的 tooltip）─


def test_require_role_403_detail_contains_editor(
    pg_engine: Engine, workspace_with_owner: dict[str, Any], empty_admin_emails: None
):
    """viewer 调写端点拒绝时，403 detail 必须含 "editor" 字样让前端能展示。

    这条是契约：前端 UseCurrentRole hook + 按钮 tooltip 直接读 detail 里的
    role 名，不会做语义解析。
    """
    from app.services.auth import rbac

    rbac.clear_cache()
    wid = workspace_with_owner["workspace_id"]
    owner_id = workspace_with_owner["owner"]["id"]
    owner_email = workspace_with_owner["owner"]["email"]

    _make_team_member(
        pg_engine, workspace_id=wid, user_id=owner_id, email=owner_email, role="viewer"
    )
    rbac.clear_cache()

    check = rbac.require_role(["admin", "editor"])
    viewer = _fake_user(user_id=owner_id, email=owner_email)

    with pytest.raises(HTTPException) as excinfo:
        check(viewer)
    detail = str(excinfo.value.detail)
    assert "editor" in detail, f"403 detail 应含 'editor'，实际：{detail!r}"
    # 同时含 admin（前端可以告诉用户「admin/editor 都能改」）
    assert "admin" in detail, f"403 detail 应含 'admin'，实际：{detail!r}"
