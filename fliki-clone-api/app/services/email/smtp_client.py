"""stdlib smtplib 薄封装（Track-22）。

提供 `send_email(message)` 一个 API：
- 接受 `EmailMessage`（自定义 dataclass，纯文本 body + 可选 PDF 附件）
- 读 `app.config.get_settings()` 的 `smtp_*` / `invoice_email_enabled` 字段
- 缺配置 → `EmailNotConfigured`（caller 翻 503 或 webhook `{sent: False}`）
- 配齐 → 真发；smtplib 抛任何 SMTP 异常都上抛（caller 决定是否吞）

不做的：
- 不读 .env 直接走 `os.environ`：所有配置统一走 `config.Settings`
- 不维护连接池：单次 webhook 触发 1 封信，开/关连接成本可接受
- 不接异步：webhook handler 已经在线程池里跑，加 asyncio 反而引复杂度
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage as StdEmailMessage
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    """SMTP 必备字段缺失（host / user / password 任一空）。

    `_handle_invoice_paid` 捕获后翻成 `{handled:True, sent:False, reason:...}`，
    避免 stripe 反复重投同一个 invoice.paid 事件打满 worker。
    """


@dataclass
class EmailMessage:
    """跨 SMTP 提供商通用的邮件 envelope。

    attachments 里每项是 ``(filename, mime_type, bytes)`` 三元组。
    PDF 走 ``("invoice.pdf", "application/pdf", b"...")``。
    """

    to: str
    subject: str
    body: str  # 纯文本
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: Optional[str] = None


def _resolve_from_address(*, smtp_from: str, smtp_user: str, smtp_host: str) -> str:
    """smtp_from > smtp_user > noreply@<smtp_host>；都缺时给一个明显的占位
    避免 SMTP relay 把信彻底拒收（reject 比悄悄送进 spam 更好排查）。
    """
    if smtp_from:
        return smtp_from
    if smtp_user and "@" in smtp_user:
        return smtp_user
    if smtp_host:
        return f"noreply@{smtp_host}"
    return "noreply@example.invalid"


def _build_mime(message: EmailMessage, *, from_addr: str) -> StdEmailMessage:
    """`EmailMessage` → stdlib `email.message.EmailMessage`（含附件）。

    用 stdlib `EmailMessage` 而非旧 `MIMEMultipart` API：set_content / add_attachment
    自动处理编码 / Content-Transfer-Encoding，不会出 Gmail 把中文标题编错的问题。
    """
    mime = StdEmailMessage()
    mime["From"] = from_addr
    mime["To"] = message.to
    if message.cc:
        mime["Cc"] = ", ".join(message.cc)
    if message.reply_to:
        mime["Reply-To"] = message.reply_to
    mime["Subject"] = message.subject
    mime.set_content(message.body, subtype="plain", charset="utf-8")

    for filename, mime_type, payload in message.attachments:
        if "/" in mime_type:
            maintype, subtype = mime_type.split("/", 1)
        else:
            maintype, subtype = "application", "octet-stream"
        mime.add_attachment(
            payload,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    return mime


def _open_smtp(
    *,
    host: str,
    port: int,
    use_ssl: bool,
    use_tls: bool,
    timeout: float = 15.0,
):
    """根据 use_ssl / use_tls 选择 SMTP_SSL / SMTP+STARTTLS。

    SSL 端口（465）走 `SMTP_SSL` 直连；STARTTLS 端口（587）走 `SMTP` + `starttls()`；
    本地测试 mailpit / smtp4dev 都监听 1025 明文，把两个 flag 都置 false 即可。
    """
    if use_ssl:
        ctx = ssl.create_default_context()
        return smtplib.SMTP_SSL(host=host, port=port, timeout=timeout, context=ctx)
    client = smtplib.SMTP(host=host, port=port, timeout=timeout)
    if use_tls:
        ctx = ssl.create_default_context()
        client.starttls(context=ctx)
    return client


def send_email(message: EmailMessage) -> dict[str, object]:
    """同步发一封邮件；失败抛 `EmailNotConfigured` 或 smtplib 异常。

    返回 ``{"to": ..., "subject": ..., "from": ..., "size_bytes": int}``，
    便于上层写日志 / 单元测试断言。
    """
    settings = get_settings()
    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_user or "").strip()
    password = (settings.smtp_password or "").strip()
    if not host or not user or not password:
        raise EmailNotConfigured(
            "SMTP 必备字段缺失："
            f"host={'set' if host else 'EMPTY'} "
            f"user={'set' if user else 'EMPTY'} "
            f"password={'set' if password else 'EMPTY'}；"
            "在 .env 配 SMTP_HOST / SMTP_USER / SMTP_PASSWORD 三件套后重启 backend"
        )

    port = int(settings.smtp_port or 587)
    use_ssl = bool(settings.smtp_use_ssl)
    use_tls = bool(settings.smtp_use_tls) and not use_ssl  # SSL 模式下不能再 STARTTLS
    from_addr = _resolve_from_address(
        smtp_from=(settings.smtp_from or "").strip(),
        smtp_user=user,
        smtp_host=host,
    )
    mime = _build_mime(message, from_addr=from_addr)

    rcpts = [message.to, *message.cc, *message.bcc]
    payload_bytes = mime.as_bytes()
    with _open_smtp(host=host, port=port, use_ssl=use_ssl, use_tls=use_tls) as client:
        client.login(user, password)
        client.send_message(mime, from_addr=from_addr, to_addrs=rcpts)

    logger.info(
        "smtp send ok to=%s subject=%s from=%s size=%d host=%s",
        message.to,
        message.subject,
        from_addr,
        len(payload_bytes),
        host,
    )
    return {
        "to": message.to,
        "subject": message.subject,
        "from": from_addr,
        "size_bytes": len(payload_bytes),
    }


__all__ = [
    "EmailMessage",
    "EmailNotConfigured",
    "send_email",
]
