"""月账单 PDF 渲染（Track-22）。

输入
----
`InvoiceContext`：包含 tenant_id / plan / period (start, end) / 期内按 provider
拆分的 cost 行 + stripe invoice 自带的 line_items + 总金额。

输出
----
A4 PDF bytes（不落盘；直接喂给 `services/email.send_email` 作附件）。

设计取舍
-------
- **不引第三方 logo**：用 reportlab Paragraph 渲文字标题（"Fliki" + 18pt bold）；
  接入真 logo 时把 `_render_header` 里的 Paragraph 换成 `Image("path/to/logo.png")`
  即可，调用方不变。
- **数据合并**：stripe invoice.lines（plan 订阅费）+ 期内 model_calls 按 provider
  聚合（实际算力消耗）两份数据各画一张表，再算总金额（plan 费 + 算力费），
  在最下方右对齐显示。
- **不依赖 PG 直连**：`build_invoice_context` 接受已查好的 `provider_breakdown`
  列表（由 caller 调 cost.py helper 取数）；这样 invoice_pdf 模块本身可以脱离
  DB 单测（保持纯函数）。
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)


# ── 输入数据结构 ─────────────────────────────────────────────────────────────


@dataclass
class ProviderCostLine:
    """期内按 provider 聚合的算力开销（来自 model_calls 表）。"""

    provider: str
    cost_usd: float
    call_count: int


@dataclass
class StripeInvoiceLine:
    """stripe invoice.lines.data 的最小子集；额外字段（taxes / discounts）
    由 caller 自行折算到 amount_usd 再传入。
    """

    description: str
    amount_usd: float
    quantity: int = 1


@dataclass
class InvoiceContext:
    """渲一张完整 PDF 需要的全部数据。"""

    tenant_id: str
    tenant_display_name: Optional[str]
    plan: str
    user_email: Optional[str]
    period_start: datetime
    period_end: datetime
    invoice_id: str  # stripe invoice id；展示在右上角
    invoice_number: Optional[str] = None  # stripe 友好编号 INV-XXXX
    currency: str = "USD"
    stripe_lines: list[StripeInvoiceLine] = field(default_factory=list)
    provider_breakdown: list[ProviderCostLine] = field(default_factory=list)
    # stripe 给的 invoice.amount_paid（cents → dollars 由 caller 折算）。
    # 缺省 None 时用 stripe_lines 之和兜底。
    amount_paid_usd: Optional[float] = None


# ── 辅助 ─────────────────────────────────────────────────────────────────────


def _fmt_money(amount: float, currency: str = "USD") -> str:
    """`123.456 USD` → `$123.46`。currency 非 USD 时显式带符号便于审计。"""
    cents = Decimal(str(amount)).quantize(Decimal("0.01"))
    if currency.upper() == "USD":
        return f"${cents}"
    return f"{cents} {currency.upper()}"


def _fmt_period(start: datetime, end: datetime) -> str:
    """`2026-04-01 → 2026-04-30 (UTC)`；只显示日期不显示时分。"""

    def _d(dt: datetime) -> date:
        return dt.astimezone(timezone.utc).date() if dt.tzinfo else dt.date()

    return f"{_d(start).isoformat()} → {_d(end).isoformat()} (UTC)"


def _stripe_total(ctx: InvoiceContext) -> float:
    if ctx.amount_paid_usd is not None:
        return float(ctx.amount_paid_usd)
    return float(sum(line.amount_usd for line in ctx.stripe_lines))


def _provider_total(ctx: InvoiceContext) -> float:
    return float(sum(line.cost_usd for line in ctx.provider_breakdown))


# ── reportlab story 构造 ─────────────────────────────────────────────────────


def _styles():
    """共享 ParagraphStyle 集；每次调一次（lru_cache 在 reportlab 上对象生命周期不友好）。"""
    base = getSampleStyleSheet()
    base.add(
        ParagraphStyle(
            name="LogoTitle",
            parent=base["Title"],
            fontSize=22,
            leading=26,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#0F766E"),  # emerald-700，与前端 cost panel 同色系
        )
    )
    base.add(
        ParagraphStyle(
            name="InvoiceMeta",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#374151"),  # gray-700
        )
    )
    base.add(
        ParagraphStyle(
            name="SectionHeader",
            parent=base["Heading2"],
            fontSize=13,
            leading=16,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#111827"),
        )
    )
    base.add(
        ParagraphStyle(
            name="GrandTotal",
            parent=base["Heading2"],
            fontSize=14,
            leading=18,
            alignment=TA_RIGHT,
            textColor=colors.HexColor("#0F766E"),
        )
    )
    return base


def _render_header(ctx: InvoiceContext, styles) -> list[Any]:
    """顶部双栏：左 logo 文字标题 + 用户/tenant 信息；右 invoice meta（编号 + 日期）。"""
    left_inner: list[Any] = [
        Paragraph("Fliki", styles["LogoTitle"]),
        Spacer(1, 4),
        Paragraph(
            f"<b>Plan:</b> {ctx.plan}", styles["Normal"]
        ),
        Paragraph(
            f"<b>Tenant:</b> {ctx.tenant_display_name or ctx.tenant_id}",
            styles["Normal"],
        ),
        Paragraph(
            f"<b>Bill to:</b> {ctx.user_email or '—'}",
            styles["Normal"],
        ),
    ]
    right_inner: list[Any] = [
        Paragraph(
            f"<b>Invoice</b> {ctx.invoice_number or ctx.invoice_id}",
            styles["InvoiceMeta"],
        ),
        Paragraph(
            f"Stripe ID: {ctx.invoice_id}",
            styles["InvoiceMeta"],
        ),
        Paragraph(
            f"Period: {_fmt_period(ctx.period_start, ctx.period_end)}",
            styles["InvoiceMeta"],
        ),
        Paragraph(
            f"Currency: {ctx.currency.upper()}",
            styles["InvoiceMeta"],
        ),
    ]
    table = Table(
        [[left_inner, right_inner]],
        colWidths=[95 * mm, 95 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return [table, Spacer(1, 14)]


def _render_stripe_lines(ctx: InvoiceContext, styles) -> list[Any]:
    """stripe invoice.lines（订阅费 / proration / 折扣）一张表 + 小计。"""
    if not ctx.stripe_lines:
        return [
            Paragraph("Subscription charges", styles["SectionHeader"]),
            Paragraph(
                "<i>No line items reported by Stripe (subscription charge captured at "
                f"<b>{_fmt_money(_stripe_total(ctx), ctx.currency)}</b>).</i>",
                styles["Normal"],
            ),
        ]
    rows: list[list[Any]] = [["Description", "Qty", "Amount"]]
    for line in ctx.stripe_lines:
        rows.append(
            [
                Paragraph(line.description, styles["Normal"]),
                str(line.quantity),
                _fmt_money(line.amount_usd, ctx.currency),
            ]
        )
    rows.append(
        [
            Paragraph("<b>Subscription subtotal</b>", styles["Normal"]),
            "",
            _fmt_money(_stripe_total(ctx), ctx.currency),
        ]
    )
    table = Table(rows, colWidths=[120 * mm, 20 * mm, 50 * mm])
    table.setStyle(_table_style(header_row=0, total_row=len(rows) - 1))
    return [
        Paragraph("Subscription charges", styles["SectionHeader"]),
        table,
    ]


def _render_provider_breakdown(ctx: InvoiceContext, styles) -> list[Any]:
    """期内 model_calls 按 provider 聚合的算力消耗表 + 小计。"""
    if not ctx.provider_breakdown:
        return [
            Paragraph("Compute usage by provider", styles["SectionHeader"]),
            Paragraph(
                "<i>No model usage recorded in this billing period.</i>",
                styles["Normal"],
            ),
        ]
    rows: list[list[Any]] = [["Provider", "Calls", "Cost"]]
    for line in ctx.provider_breakdown:
        rows.append(
            [
                Paragraph(line.provider, styles["Normal"]),
                str(line.call_count),
                _fmt_money(line.cost_usd, ctx.currency),
            ]
        )
    rows.append(
        [
            Paragraph("<b>Compute subtotal</b>", styles["Normal"]),
            "",
            _fmt_money(_provider_total(ctx), ctx.currency),
        ]
    )
    table = Table(rows, colWidths=[120 * mm, 20 * mm, 50 * mm])
    table.setStyle(_table_style(header_row=0, total_row=len(rows) - 1))
    return [
        Paragraph("Compute usage by provider", styles["SectionHeader"]),
        table,
    ]


def _render_total(ctx: InvoiceContext, styles) -> list[Any]:
    """总金额 = stripe 订阅费 + 期内算力消耗。"""
    grand = _stripe_total(ctx) + _provider_total(ctx)
    return [
        Spacer(1, 16),
        Paragraph(
            f"<b>Total</b>: {_fmt_money(grand, ctx.currency)}",
            styles["GrandTotal"],
        ),
        Spacer(1, 4),
        Paragraph(
            "<i>Subscription charge billed by Stripe. "
            "Compute usage shown for transparency only — no separate charge.</i>",
            styles["Normal"],
        ),
    ]


def _table_style(*, header_row: int, total_row: int) -> TableStyle:
    """两份表格共享：header 浅 emerald 背景 + 总计行细灰线。"""
    return TableStyle(
        [
            ("BACKGROUND", (0, header_row), (-1, header_row), colors.HexColor("#D1FAE5")),
            ("TEXTCOLOR", (0, header_row), (-1, header_row), colors.HexColor("#064E3B")),
            ("FONTNAME", (0, header_row), (-1, header_row), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, header_row + 1), (-1, total_row - 1),
             [colors.white, colors.HexColor("#F9FAFB")]),
            ("LINEABOVE", (0, total_row), (-1, total_row), 0.5, colors.HexColor("#9CA3AF")),
            ("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]
    )


# ── 公开 API ─────────────────────────────────────────────────────────────────


def render_invoice_pdf(ctx: InvoiceContext) -> bytes:
    """渲一张完整 invoice PDF；返回 bytes，不落盘。

    任何 reportlab 内部异常都直接上抛，由 webhook handler 翻成
    `{handled:True, sent:False, reason:"pdf render failed: ..."}`。
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Fliki Invoice {ctx.invoice_number or ctx.invoice_id}",
        author="Fliki",
    )
    styles = _styles()
    story: list[Any] = []
    story.extend(_render_header(ctx, styles))
    story.extend(_render_stripe_lines(ctx, styles))
    story.extend(_render_provider_breakdown(ctx, styles))
    story.extend(_render_total(ctx, styles))
    doc.build(story)
    raw = buf.getvalue()
    buf.close()
    return raw


def build_filename(ctx: InvoiceContext) -> str:
    """`fliki-invoice-2026-04-INV-1234.pdf` 风格附件名。"""
    period = ctx.period_end.astimezone(timezone.utc) if ctx.period_end.tzinfo else ctx.period_end
    yyyymm = period.strftime("%Y-%m")
    label = ctx.invoice_number or ctx.invoice_id
    safe_label = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)[:40]
    return f"fliki-invoice-{yyyymm}-{safe_label}.pdf"


__all__ = [
    "InvoiceContext",
    "ProviderCostLine",
    "StripeInvoiceLine",
    "build_filename",
    "render_invoice_pdf",
]
