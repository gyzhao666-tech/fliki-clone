"""发布执行器 v1 测试（dry-run / youtube / bilibili / 重复 / 未知平台 fallback）。

覆盖
----
adapter 单元层：
1. ``test_dry_run_adapter_unit_returns_mock_external_id``    DryRunAdapter pure unit
2. ``test_bilibili_adapter_unit_returns_not_implemented``    BilibiliAdapter stub 返清晰错误
3. ``test_youtube_adapter_no_credentials_returns_failure``   YouTube 缺 access_token 友好失败
4. ``test_get_adapter_unknown_platform_falls_back_to_dry_run`` 注册表 unknown 平台兜底

executor 集成层（DB）：
5. ``test_execute_publish_plan_dry_run_full_path``           dry-run 端到端 plan→executor→published
6. ``test_execute_publish_plan_repeat_rejects_when_published``重复执行已 published 的拒绝
7. ``test_execute_publish_plan_unknown_platform_uses_dry_run``unknown 平台落库后被 executor 兜底
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.publishing


# ── 1. adapter unit ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dry_run_adapter_unit_returns_mock_external_id():
    """DryRunAdapter 永远成功，external_id 形如 ``dryrun-{plan8}-{ts}``。"""
    from app.services.publishing.adapters.base import PublishRequest
    from app.services.publishing.adapters.dry_run import DryRunAdapter

    req = PublishRequest(
        plan_id="abcdef1234567890",
        user_id="u1",
        platform="dry-run",
        file_id="f1",
        run_id=None,
        render_id=None,
        render_url="https://test.local/v.mp4",
        cover_url=None,
        title="hello",
        description=None,
        tags=["t1"],
    )
    out = DryRunAdapter().upload(req)
    assert out.ok is True
    assert out.status == "published"
    assert out.external_id and out.external_id.startswith("dryrun-abcdef12-")
    assert out.external_url and out.external_url.startswith("https://dry-run.local/")
    assert out.published_at is not None
    assert out.meta["platform"] == "dry-run"
    assert out.meta["title"] == "hello"


@pytest.mark.unit
def test_bilibili_adapter_unit_returns_not_implemented():
    """BilibiliAdapter 当前是 stub：返 ok=False + 引导手动上传文案。"""
    from app.services.publishing.adapters.base import PublishRequest
    from app.services.publishing.adapters.bilibili import BilibiliAdapter

    req = PublishRequest(
        plan_id="bili-1",
        user_id="u",
        platform="bilibili",
        file_id="f",
        run_id=None,
        render_id=None,
        render_url="https://test.local/v.mp4",
        cover_url=None,
        title="hi",
        description=None,
    )
    out = BilibiliAdapter().upload(req)
    assert out.ok is False
    assert out.status == "failed"
    assert "bilibili" in (out.error or "").lower()
    assert "https://test.local/v.mp4" in (out.error or "")
    assert out.meta["stub"] is True


@pytest.mark.unit
def test_youtube_adapter_no_credentials_returns_failure(monkeypatch):
    """YouTube 缺 GOOGLE_CLIENT_ID 或缺 access_token 时不抛异常，返 ok=False + 友好错误。

    安全闸门：即使 token 齐全，confirm_real_publish=False 时不真发，返
    mock external_id（v1 行为）。
    """
    from app.services.publishing.adapters.base import PublishRequest
    from app.services.publishing.adapters.youtube import YouTubeAdapter

    req_no_cred = PublishRequest(
        plan_id="yt-1",
        user_id="u",
        platform="youtube",
        file_id="f",
        run_id=None,
        render_id=None,
        render_url="https://test.local/v.mp4",
        cover_url=None,
        title="hi",
        description=None,
        tags=[],
        credential={
            "access_token": None,
            "refresh_token": None,
            "scope": [],
        },
    )

    # patch settings 注入 client_id/secret，让 adapter 越过第一道防线，落到 access_token check
    from app import config as cfg_mod

    real_get = cfg_mod.get_settings
    s = real_get()
    monkeypatch.setattr(
        s, "google_client_id", "fake-client-id", raising=False
    )
    monkeypatch.setattr(
        s, "google_client_secret", "fake-client-secret", raising=False
    )

    out = YouTubeAdapter().upload(req_no_cred)
    assert out.ok is False
    assert out.status == "failed"
    assert "authoriz" in (out.error or "").lower() or "oauth" in (out.error or "").lower()

    # 反过来：完全没配 client_id → 返「需要 GOOGLE_CLIENT_ID」错误
    monkeypatch.setattr(s, "google_client_id", "", raising=False)
    out2 = YouTubeAdapter().upload(req_no_cred)
    assert out2.ok is False
    assert "GOOGLE_CLIENT_ID" in (out2.error or "")


@pytest.mark.unit
def test_get_adapter_unknown_platform_falls_back_to_dry_run():
    """``get_adapter('weibo-mock')`` 注册表 miss → 返 DryRunAdapter 实例（不抛）。"""
    from app.services.publishing.adapters import get_adapter
    from app.services.publishing.adapters.dry_run import DryRunAdapter

    a = get_adapter("weibo-mock-unknown-plat")
    assert isinstance(a, DryRunAdapter)


# ── 2. executor 集成（需要 PG） ─────────────────────────────────────────────


def _insert_plan(
    pg_engine,
    *,
    file_id: str,
    platform: str = "dry-run",
    status: str = "draft",
    render_id: str | None = None,
    run_id: str | None = None,
    title: str = "pytest plan",
    confirm_real_publish: bool = False,
    meta_json: dict | None = None,
) -> str:
    """工具：往 publish_plans 插一行；返 plan_id。"""
    pid = f"test_p_{uuid.uuid4().hex[:10]}"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO publish_plans
                    (id, file_id, run_id, render_id, platform, status,
                     title, description, tags_json, meta_json,
                     confirm_real_publish, created_at, updated_at)
                VALUES
                    (:id, :f, :run, :ren, :pf, :st,
                     :t, NULL, CAST(:tags AS JSON), CAST(:meta AS JSON),
                     :crp, NOW(), NOW())
                """
            ),
            {
                "id": pid,
                "f": file_id,
                "run": run_id,
                "ren": render_id,
                "pf": platform,
                "st": status,
                "t": title,
                "tags": json.dumps([]),
                "meta": json.dumps(meta_json or {}),
                "crp": confirm_real_publish,
            },
        )
    return pid


@pytest.mark.integration
def test_execute_publish_plan_dry_run_full_path(pg_engine, temp_render):
    """端到端：插一条 dry-run plan → execute → DB 行 status=published + external_id 写回。"""
    from app.services.publishing import execute_publish_plan

    file_id = temp_render["file_id"]
    user_id = pg_engine.connect().execute(
        text("SELECT user_id FROM files WHERE id = :f"), {"f": file_id}
    ).scalar_one()

    plan_id = _insert_plan(
        pg_engine,
        file_id=file_id,
        platform="dry-run",
        render_id=temp_render["id"],
        run_id=temp_render["run_id"],
    )

    outcome = execute_publish_plan(plan_id, user_id=user_id)
    assert outcome.ok is True
    assert outcome.external_id and outcome.external_id.startswith("dryrun-")
    assert outcome.status == "published"

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT status, external_id, published_at, error FROM publish_plans "
                "WHERE id = :id"
            ),
            {"id": plan_id},
        ).fetchone()
    assert row is not None
    assert row[0] == "published"
    assert row[1] == outcome.external_id
    assert row[2] is not None
    assert row[3] is None  # error 列应空


@pytest.mark.integration
def test_execute_publish_plan_repeat_rejects_when_published(pg_engine, temp_render):
    """已 published 的 plan 再 execute → 拒绝（ok=False, error 提示先 reset）。"""
    from app.services.publishing import execute_publish_plan

    file_id = temp_render["file_id"]
    user_id = pg_engine.connect().execute(
        text("SELECT user_id FROM files WHERE id = :f"), {"f": file_id}
    ).scalar_one()

    plan_id = _insert_plan(
        pg_engine,
        file_id=file_id,
        platform="dry-run",
        status="published",
        render_id=temp_render["id"],
        run_id=temp_render["run_id"],
    )

    outcome = execute_publish_plan(plan_id, user_id=user_id)
    assert outcome.ok is False
    assert "already published" in (outcome.error or "").lower()


@pytest.mark.integration
def test_execute_publish_plan_unknown_platform_uses_dry_run(pg_engine, temp_render):
    """plan.platform='weibo-not-real' → executor 通过 get_adapter 兜底到 dry-run，仍写 published。

    这是 v1 的容错策略：不让前端因为 enum 不匹配 status=draft 永久卡住，
    而是给一个温和的可观测的「假发」记录。
    """
    from app.services.publishing import execute_publish_plan

    file_id = temp_render["file_id"]
    user_id = pg_engine.connect().execute(
        text("SELECT user_id FROM files WHERE id = :f"), {"f": file_id}
    ).scalar_one()

    plan_id = _insert_plan(
        pg_engine,
        file_id=file_id,
        platform="weibo-not-real",
        render_id=temp_render["id"],
        run_id=temp_render["run_id"],
    )

    outcome = execute_publish_plan(plan_id, user_id=user_id)
    assert outcome.ok is True, f"未知平台应 fallback dry-run：{outcome.error}"
    assert outcome.external_id and outcome.external_id.startswith("dryrun-")

    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, external_id FROM publish_plans WHERE id = :id"),
            {"id": plan_id},
        ).fetchone()
    assert row[0] == "published"
    assert row[1] == outcome.external_id


@pytest.mark.integration
def test_execute_publish_plan_youtube_no_cred_writes_failure(pg_engine, temp_render):
    """plan.platform='youtube' 但 user 没绑 OAuth → executor 写 plan.status='failed' +
    plan.error 含「requires OAuth」字样，且不抛异常（只是返 ok=False）。
    """
    from app.services.publishing import execute_publish_plan

    file_id = temp_render["file_id"]
    user_id = pg_engine.connect().execute(
        text("SELECT user_id FROM files WHERE id = :f"), {"f": file_id}
    ).scalar_one()

    plan_id = _insert_plan(
        pg_engine,
        file_id=file_id,
        platform="youtube",
        render_id=temp_render["id"],
        run_id=temp_render["run_id"],
    )
    # 故意没 platform_credentials 行；executor 应在 get_credential() 拿到 None
    outcome = execute_publish_plan(plan_id, user_id=user_id)
    assert outcome.ok is False
    assert outcome.status == "failed"
    assert "OAuth" in (outcome.error or "")

    with pg_engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, error FROM publish_plans WHERE id = :id"),
            {"id": plan_id},
        ).fetchone()
    assert row[0] == "failed"
    assert "OAuth" in (row[1] or "")
