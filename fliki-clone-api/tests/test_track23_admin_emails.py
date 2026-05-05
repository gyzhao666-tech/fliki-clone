"""Track-23 · ADMIN_EMAILS 从 env 直读迁回 `Settings.admin_emails`。

覆盖 6 case
-----------
1. ``test_settings_default_admin_emails_is_demo``       Settings.admin_emails 默认值就是 demo@example.com
2. ``test_allowed_admins_fallback_when_env_missing``    env 缺省 → fallback {"demo@example.com"}
3. ``test_allowed_admins_single_email_from_env``        env 单邮箱 → 单元素 set + lower
4. ``test_allowed_admins_multi_email_with_spaces``      env 多逗号 + 空白 + 大小写 → split + strip + lower 正确
5. ``test_allowed_admins_empty_string_fallback``        env 显式 ""/" , , " → 解析为空 → fallback
6. ``test_is_admin_email_pipeline_with_settings``       env 切 admin → _is_admin_email 联动新名单 + 老 demo 失效

为什么不复用 test_admin_flags.py
-------------------------------
- T-14 测试关注「白名单 / CRUD / /me / /tenants」业务行为；
- T-23 测试关注「迁移到 settings 后的解析管道 + 边界」，独立文件方便回归
  时一眼看出是迁移层的事。
- 所有 case 都：先 cleanup env + ``get_settings.cache_clear()`` 才进
  ``_allowed_admins``，确保 pydantic-settings 读到本 case 期望的 env，
  避免 lru_cache 与 case 顺序耦合。
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── helpers ──────────────────────────────────────────────────────────────────


def _reset_settings(monkeypatch: pytest.MonkeyPatch, *, env_value: str | None) -> None:
    """统一的 env + cache 重置：让下次 ``get_settings()`` 重新读 env。

    - ``env_value=None`` → delenv（让 Settings 走字段默认 demo@example.com）
    - 其它 → setenv 显式赋值（含空字符串、含空白、含大小写都能传进来）
    """
    from app.config import get_settings

    if env_value is None:
        monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    else:
        monkeypatch.setenv("ADMIN_EMAILS", env_value)
    get_settings.cache_clear()


# ── 1. Settings 字段本身 ────────────────────────────────────────────────────


def test_settings_default_admin_emails_is_demo(monkeypatch: pytest.MonkeyPatch):
    """没有 env 时，Settings.admin_emails 字段默认值即 ``demo@example.com``。

    验证 Track-23 加在 ``app/config.py`` 的字段定义本身正确（pydantic-settings
    读到 env 缺省后落到 class 默认值）。
    """
    _reset_settings(monkeypatch, env_value=None)
    from app.config import get_settings

    s = get_settings()
    assert s.admin_emails == "demo@example.com"


# ── 2. _allowed_admins 解析管道 ─────────────────────────────────────────────


def test_allowed_admins_fallback_when_env_missing(monkeypatch: pytest.MonkeyPatch):
    """env 缺省 → settings 走默认 → ``_allowed_admins`` 返 {"demo@example.com"}。"""
    _reset_settings(monkeypatch, env_value=None)
    from app.routers.admin_flags import _allowed_admins

    assert _allowed_admins() == {"demo@example.com"}


def test_allowed_admins_single_email_from_env(monkeypatch: pytest.MonkeyPatch):
    """env 单邮箱 → set 化 + lower。原大小写邮箱不会泄漏。"""
    _reset_settings(monkeypatch, env_value="Ops@Example.COM")
    from app.routers.admin_flags import _allowed_admins

    out = _allowed_admins()
    assert out == {"ops@example.com"}
    assert "Ops@Example.COM" not in out  # 大小写已归一


def test_allowed_admins_multi_email_with_spaces(monkeypatch: pytest.MonkeyPatch):
    """env 多邮箱 + 逗号 + 空白 + 大小写：split + strip + lower 全链路正确。

    顺手验证：trailing 逗号 / 内部双逗号 / 仅空白条目都能被去掉，不污染白名单。
    """
    _reset_settings(
        monkeypatch,
        env_value=" Alice@x.com ,bob@Y.com,, , CAROL@Z.IO,",
    )
    from app.routers.admin_flags import _allowed_admins

    out = _allowed_admins()
    assert out == {"alice@x.com", "bob@y.com", "carol@z.io"}


def test_allowed_admins_empty_string_fallback(monkeypatch: pytest.MonkeyPatch):
    """env 显式空串（或全是分隔符 / 空白）→ 解析后无元素 → fallback demo。

    保证「ADMIN_EMAILS=」或「ADMIN_EMAILS=  ,  ,」不会让白名单空掉到无人能 admin
    （那样 fixtures 里的 demo 用户也会失权，破坏 dev / 测试体验）。
    """
    for sentinel in ("", "   ", " , , ", ",,,"):
        _reset_settings(monkeypatch, env_value=sentinel)
        from app.routers.admin_flags import _allowed_admins

        assert _allowed_admins() == {"demo@example.com"}, (
            f"env={sentinel!r} 应当 fallback 到 demo，实际 {_allowed_admins()!r}"
        )


# ── 3. 与 _is_admin_email 联动 ─────────────────────────────────────────────


def test_is_admin_email_pipeline_with_settings(monkeypatch: pytest.MonkeyPatch):
    """Track-23 后 `_is_admin_email` 仍是 `_allowed_admins` 的薄包装：
    env 切到新白名单后，新邮箱命中 / 老 demo 失效；大小写不敏感。

    这是「Track-10 / 14 / 18 既有 case 在 fallback 下仍 PASS」的反向保险：
    一旦运维 env 显式覆盖，新名单立即生效，不需要重启 / 不需要清模块。
    """
    _reset_settings(monkeypatch, env_value="alice@x.com,bob@y.com")
    from app.routers.admin_flags import _is_admin_email

    assert _is_admin_email("alice@x.com") is True
    assert _is_admin_email("Alice@X.COM") is True  # 大小写不敏感
    assert _is_admin_email("bob@y.com") is True
    assert _is_admin_email("demo@example.com") is False  # 显式覆盖后老 demo 不再 admin
    assert _is_admin_email(None) is False
    assert _is_admin_email("") is False
