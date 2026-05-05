"""轻量邮件发送层（Track-22 月账单 PDF 附件邮件）。

为什么单拎一个 `services/email/`
-------------------------------
- 只做「webhook 触发的同步发送」一件事；不引第三方（fastapi-mail 是异步用的，
  跟 stripe webhook 同步路径不匹配）。stdlib `smtplib` + `email.message`
  足够覆盖 99% 的事务邮件 + 二进制附件需求。
- 保持「缺配置就友好降级」：缺 SMTP_HOST / USER / PASSWORD 三件套任意一个 →
  `EmailNotConfigured`；上层 `_handle_invoice_paid` 翻成
  `{handled:True, sent:False, reason:...}`，让 stripe 不重投 webhook。
- 可观测：只用 stdlib logging，不写 DB（避免在 webhook 同步路径里加副作用表），
  ops 想留痕就接 logger handler。

设计取舍
-------
- **不重试**：smtplib 抛异常直接上抛；webhook 已经被 stripe 重试机制兜了，
  本层加重试只会让 stripe 同事件触发多次 send。
- **不并发**：一次发一封 + 同步阻塞；月账单频次低（每 tenant 每月 1 封），
  TPS 不是问题。
- **不验签发件人**：DKIM / SPF / DMARC 由 SMTP relay（Resend / SES / Mailgun）
  自己处理；本层只负责拼 RFC 5322 message + 喂给 smtplib。
"""
from __future__ import annotations

from .smtp_client import (
    EmailMessage,
    EmailNotConfigured,
    send_email,
)

__all__ = [
    "EmailMessage",
    "EmailNotConfigured",
    "send_email",
]
