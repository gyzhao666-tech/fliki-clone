"""Track-22 月账单 PDF + 邮件单测。

覆盖矩阵
--------
1. ``test_render_invoice_pdf_returns_valid_pdf_bytes``
   - reportlab 渲 PDF 字节非空 + 以 ``%PDF-`` 开头 + ``/Title`` 元数据含发票号
2. ``test_render_invoice_pdf_includes_provider_and_plan_in_metadata``
   - 通过 PDF Title 元数据断言发票号；通过 build_filename 断言 plan / 期 / 编号
     都进了附件名（PDF 内文本被 reportlab 压缩流隐藏，借文件名做语义校验）
3. ``test_smtp_send_raises_email_not_configured_when_host_missing``
   - 缺 SMTP_HOST 时 ``send_email`` 抛 ``EmailNotConfigured``
4. ``test_handle_invoice_paid_skipped_when_email_disabled``
   - 主开关 ``invoice_email_enabled=False`` 时 handler 直接返
     ``{handled:True, sent:False, reason:"invoice_email_enabled=false"}``
5. ``test_handle_invoice_paid_skipped_when_smtp_not_configured``
   - 开关开 + SMTP 缺配置 → ``sent:False, reason 含 "smtp not configured"``
6. ``test_handle_invoice_paid_calls_send_email_when_fully_configured``
   - 开关开 + SMTP 配齐 + monkeypatch ``send_email`` → handler 真调 send，
     携带 PDF 附件且 ``to == user.email``，handler 返 ``sent:True``
7. ``test_handle_invoice_paid_skipped_when_user_email_missing``
   - user_id 解析得到但 users.email 为空字符串 → ``sent:False, reason 含 'user.email empty'``

设计取舍
-------
- PDF 内文本被 reportlab 压缩，不能 substring 检；改用 ``/Title`` PDF metadata
  断言（始终明文）+ ``build_filename`` 断言 plan / 期。
- 不污染 conftest：``make_invoice_event`` / ``make_ctx`` helper 私有在本文件。
- 缺 SMTP 走 monkeypatch ``smtp_host`` 字段而非真启假 SMTP server，避免端口竞争。
- handler 集成 case 走真 PG（与 test_billing_webhook.py 一致），用同一个
  ``billing_user`` fixture 风格 inline 复刻；teardown 自带。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import text


# ── helper ────────────────────────────────────────────────────────────────────


def _make_ctx(**overrides: Any):
    """构造一个 InvoiceContext 默认值，case 用 overrides 覆盖局部字段。"""
    from app.services.billing.invoice_pdf import (
        InvoiceContext,
        ProviderCostLine,
        StripeInvoiceLine,
    )

    base = dict(
        tenant_id="u:demo-user",
        tenant_display_name="Demo Tenant",
        plan="standard",
        user_email="alice@example.com",
        period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 4, 30, tzinfo=timezone.utc),
        invoice_id="in_test_abc123",
        invoice_number="INV-0042",
        currency="USD",
        stripe_lines=[
            StripeInvoiceLine(description="Standard plan (monthly)", amount_usd=29.0)
        ],
        provider_breakdown=[
            ProviderCostLine(provider="siliconflow", cost_usd=12.34, call_count=120),
            ProviderCostLine(provider="openai", cost_usd=4.56, call_count=12),
        ],
        amount_paid_usd=29.0,
    )
    base.update(overrides)
    return InvoiceContext(**base)


def _make_invoice_event(
    *,
    user_id: Optional[str] = None,
    customer_id: str = "cus_test_xxx",
    sub_id: str = "sub_test_xxx",
    invoice_id: str = "in_test_paid_001",
) -> dict[str, Any]:
    """构造一个最小可用的 stripe invoice.paid event dict。"""
    period_end_ts = int(datetime(2026, 4, 30, tzinfo=timezone.utc).timestamp())
    period_start_ts = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp())
    metadata: dict[str, Any] = {}
    if user_id:
        metadata["user_id"] = user_id
    return {
        "id": f"evt_invoice_{uuid.uuid4().hex[:8]}",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": invoice_id,
                "number": "INV-0042",
                "customer": customer_id,
                "subscription": sub_id,
                "currency": "usd",
                "amount_paid": 2900,  # cents
                "period_start": period_start_ts,
                "period_end": period_end_ts,
                "metadata": metadata,
                "lines": {
                    "data": [
                        {
                            "description": "Standard plan",
                            "amount": 2900,
                            "quantity": 1,
                            "period": {
                                "start": period_start_ts,
                                "end": period_end_ts,
                            },
                        }
                    ]
                },
            }
        },
    }


# ── 1. PDF 渲染基础 ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_render_invoice_pdf_returns_valid_pdf_bytes():
    from app.services.billing.invoice_pdf import render_invoice_pdf

    pdf = render_invoice_pdf(_make_ctx())
    assert isinstance(pdf, bytes)
    assert len(pdf) > 1000  # A4 + 表格 + header 至少 1KB
    assert pdf.startswith(b"%PDF-")
    # %%EOF 是 PDF 终止标记，确保不是被截断的输出
    assert b"%%EOF" in pdf[-64:] or b"%%EOF" in pdf


@pytest.mark.unit
def test_render_invoice_pdf_includes_invoice_id_in_metadata_and_filename():
    """PDF 内文本被 reportlab 压缩，借 ``/Title`` 元数据 + 文件名断言关键字段。"""
    from app.services.billing.invoice_pdf import build_filename, render_invoice_pdf

    ctx = _make_ctx(invoice_number="INV-9999", invoice_id="in_pdf_check_xyz")
    pdf = render_invoice_pdf(ctx)
    raw = pdf.decode("latin-1", errors="ignore")
    # PDF Document Title 是明文，render_invoice_pdf 设的是 "Fliki Invoice {number or id}"
    assert "/Title" in raw
    assert "INV-9999" in raw
    assert "Fliki" in raw

    fn = build_filename(ctx)
    assert fn.endswith(".pdf")
    assert "2026-04" in fn  # period_end 的年-月
    assert "INV-9999" in fn


# ── 2. SMTP 客户端缺配置 ────────────────────────────────────────────────────


@pytest.mark.unit
def test_smtp_send_raises_email_not_configured_when_host_missing(monkeypatch):
    """缺 SMTP_HOST → EmailNotConfigured；上层翻 sent:False 不让 stripe 重投。"""
    from app.config import get_settings
    from app.services.email import EmailMessage, EmailNotConfigured, send_email

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "alice@example.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")

    msg = EmailMessage(
        to="bob@example.com",
        subject="hi",
        body="hello",
        attachments=[("a.pdf", "application/pdf", b"fake-pdf-bytes")],
    )
    with pytest.raises(EmailNotConfigured):
        send_email(msg)


# ── 3. _handle_invoice_paid 主开关关闭 ──────────────────────────────────────


@pytest.mark.unit
def test_handle_invoice_paid_skipped_when_email_disabled(monkeypatch):
    """invoice_email_enabled=False 时 handler 直接 short-circuit；不读 DB / 不发信。"""
    from app.config import get_settings
    from app.services.billing import webhook_handlers

    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_email_enabled", False)

    event = _make_invoice_event(user_id="u-doesnt-matter")
    result = webhook_handlers.handle_webhook_event(event)

    assert result["handled"] is True
    assert result["sent"] is False
    assert result["type"] == "invoice.paid"
    assert "invoice_email_enabled=false" in result["reason"]


# ── 4. _handle_invoice_paid SMTP 缺配置 ─────────────────────────────────────


@pytest.mark.integration
def test_handle_invoice_paid_skipped_when_smtp_not_configured(
    pg_engine, monkeypatch
):
    """开关开 + SMTP 缺 → ``sent:False, reason 含 'smtp not configured'``。

    走真 PG：seed 一条 user + subscription，让 user_id 能被解析到，否则
    handler 在「user 解析」环节就 return 了，覆盖不到 smtp 分支。
    """
    from app.config import get_settings
    from app.services.billing import webhook_handlers

    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_email_enabled", True)
    # 强制 smtp_host 空，确保 SMTP 缺配置
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")

    user_id, sub_id, customer_id = _seed_user_with_sub(pg_engine, plan="standard")
    try:
        event = _make_invoice_event(
            user_id=user_id, customer_id=customer_id, sub_id=sub_id
        )
        result = webhook_handlers.handle_webhook_event(event)

        assert result["handled"] is True
        assert result["sent"] is False
        assert "smtp not configured" in result["reason"]
        assert result["invoice_id"] == event["data"]["object"]["id"]
    finally:
        _cleanup_user_with_sub(pg_engine, user_id=user_id)


# ── 5. _handle_invoice_paid 全部就绪 → 真发 ─────────────────────────────────


@pytest.mark.integration
def test_handle_invoice_paid_calls_send_email_when_fully_configured(
    pg_engine, monkeypatch
):
    """开关开 + SMTP 配齐 + monkeypatch send_email → handler 真调；
    携带 PDF 附件且 to == user.email；返 sent:True。
    """
    from app.config import get_settings
    from app.services.billing import webhook_handlers

    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "noreply@example.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_from", "billing@example.com")

    user_id, sub_id, customer_id = _seed_user_with_sub(
        pg_engine, plan="standard", email="alice-track22@pytest.local"
    )

    captured: dict[str, Any] = {}

    def _fake_send_email(message):
        captured["to"] = message.to
        captured["subject"] = message.subject
        captured["body"] = message.body
        captured["attachments"] = list(message.attachments)
        return {"to": message.to, "subject": message.subject, "from": "x", "size_bytes": 1}

    # 让 webhook_handlers 内部 `from app.services.email import ... send_email` 拿到 fake
    import app.services.email as email_module

    monkeypatch.setattr(email_module, "send_email", _fake_send_email)

    try:
        event = _make_invoice_event(
            user_id=user_id, customer_id=customer_id, sub_id=sub_id
        )
        result = webhook_handlers.handle_webhook_event(event)

        assert result["handled"] is True
        assert result["sent"] is True
        assert result["email_to"] == "alice-track22@pytest.local"
        assert result["pdf_size"] > 1000

        assert captured["to"] == "alice-track22@pytest.local"
        assert "Fliki invoice" in captured["subject"]
        assert "INV-0042" in captured["subject"]
        # body 含 plan / 期 / invoice_id 关键字段，便于用户在邮件正文也能看到
        assert "standard" in captured["body"]
        assert "2026-04-01" in captured["body"]
        assert "2026-04-30" in captured["body"]
        assert event["data"]["object"]["id"] in captured["body"]

        assert len(captured["attachments"]) == 1
        fn, mime, payload = captured["attachments"][0]
        assert fn.endswith(".pdf")
        assert "INV-0042" in fn
        assert mime == "application/pdf"
        assert payload.startswith(b"%PDF-")
    finally:
        _cleanup_user_with_sub(pg_engine, user_id=user_id)


# ── 6. _handle_invoice_paid 用户 email 缺失 ─────────────────────────────────


@pytest.mark.integration
def test_handle_invoice_paid_skipped_when_user_email_missing(
    pg_engine, monkeypatch
):
    """user_id 解析得到但 users.email 为空字符串 → ``sent:False, reason='user.email empty ...'``。

    模拟「用户走 OAuth 但未 verify email」场景；不能让 webhook 抛 500 让 stripe 重投。
    """
    from app.config import get_settings
    from app.services.billing import webhook_handlers

    settings = get_settings()
    monkeypatch.setattr(settings, "invoice_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_user", "noreply@example.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")

    user_id, sub_id, customer_id = _seed_user_with_sub(
        pg_engine, plan="standard", email="placeholder-track22@pytest.local"
    )
    # 把 email 改成空串模拟未 verify 场景
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE users SET email = '' WHERE id = :u"),
            {"u": user_id},
        )

    try:
        event = _make_invoice_event(
            user_id=user_id, customer_id=customer_id, sub_id=sub_id
        )
        result = webhook_handlers.handle_webhook_event(event)
        assert result["handled"] is True
        assert result["sent"] is False
        assert "user.email empty" in result["reason"]
    finally:
        _cleanup_user_with_sub(pg_engine, user_id=user_id)


# ── DB seed / teardown helpers ───────────────────────────────────────────────


def _seed_user_with_sub(
    pg_engine,
    *,
    plan: str = "standard",
    email: Optional[str] = None,
) -> tuple[str, str, str]:
    """seed user + subscription（active），返 (user_id, sub_id, customer_id)。"""
    user_id = f"test_u_{uuid.uuid4().hex[:8]}"
    sub_id = f"sub_test_{uuid.uuid4().hex[:8]}"
    customer_id = f"cus_test_{uuid.uuid4().hex[:8]}"
    user_email = email or f"{user_id}@pytest.local"
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users
                    (id, email, name, hashed_password, plan,
                     credits_used, credits_total, email_notifications,
                     youtube_channel_ids, created_at, updated_at)
                VALUES
                    (:id, :em, 'pytest user', '!', :pl,
                     0, 0, false, '{}', NOW(), NOW())
                """
            ),
            {"id": user_id, "em": user_email, "pl": plan},
        )
        conn.execute(
            text(
                """
                INSERT INTO subscriptions
                    (id, user_id, stripe_sub_id, stripe_customer_id,
                     plan, status, current_period_end, created_at, updated_at)
                VALUES
                    (:id, :u, :sid, :cid, :pl, 'active', NULL, NOW(), NOW())
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "u": user_id,
                "sid": sub_id,
                "cid": customer_id,
                "pl": plan,
            },
        )
    return user_id, sub_id, customer_id


def _cleanup_user_with_sub(pg_engine, *, user_id: str) -> None:
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM subscriptions WHERE user_id = :u"),
            {"u": user_id},
        )
        conn.execute(
            text("DELETE FROM tenant_quotas WHERE tenant_id = :t"),
            {"t": f"u:{user_id}"},
        )
        conn.execute(
            text("DELETE FROM users WHERE id = :u"),
            {"u": user_id},
        )
