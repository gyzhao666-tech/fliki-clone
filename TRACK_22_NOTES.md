# Track-22 · 月账单 PDF + 邮件 交付备忘

**分支**：`track-22-invoice-pdf-email`
**基线 commit**：`ff48c75`（第五波 backlog 派发点）
**完成 commit**：见 `git log -1 track-22-invoice-pdf-email`
**测试结果**：`cd fliki-clone-api && make test` → **96 passed**（89 baseline + 7 新增）

## 1. 改了什么 / 为什么

### 1.1 新增模块（独占）

| 文件 | 用途 |
|---|---|
| `fliki-clone-api/app/services/billing/invoice_pdf.py` | reportlab 渲 A4 PDF（Fliki 文字 logo + tenant/plan/期间 + stripe lines 表 + 按 provider 拆分的 model_calls 算力表 + 总金额）。纯函数，喂 `InvoiceContext` 出 `bytes`，不落盘 |
| `fliki-clone-api/app/services/email/__init__.py` | 简单 re-export `EmailMessage / EmailNotConfigured / send_email` |
| `fliki-clone-api/app/services/email/smtp_client.py` | stdlib `smtplib` 薄封装，不引第三方。缺 `SMTP_HOST/USER/PASSWORD` 抛 `EmailNotConfigured`；支持 STARTTLS（587）/ SSL（465）/ 明文（mailpit 1025） |
| `fliki-clone-api/tests/test_track22_invoice_email.py` | 7 case 覆盖 PDF 渲染 / 文件名 / SMTP 缺配置 / handler 4 路径分支 |

### 1.2 修改文件

| 文件 | 改动 | 不动的部分 |
|---|---|---|
| `fliki-clone-api/app/config.py` | 加 8 字段：`smtp_host/port/user/password/from/use_tls/use_ssl + invoice_email_enabled` | **没动 admin_emails 相关**（留给 T-23） |
| `fliki-clone-api/app/services/billing/webhook_handlers.py` | (1) 模块 docstring 加 invoice.paid 行 + 设计取舍段落；(2) `handle_webhook_event` 末尾加 `if event_type == "invoice.paid":` 分支；(3) 新加 `_handle_invoice_paid` + 4 个私有 helper（`_invoice_skip` / `_resolve_invoice_period` / `_build_invoice_context` / `_fetch_provider_breakdown_for_period` / `_invoice_email_body`）；(4) 新加 2 个 DB helper（`_user_id_for_customer` / `_fetch_user_for_invoice`） | **既有 5 handler 函数体一行未改**（checkout / sub.updated / sub.deleted / invoice.payment_failed / charge.refunded）；既有 `_engine` / `_upsert_subscription` / `_mark_*` 等 DB helper 一字未改；dispatch 入口 `handle_webhook_event` 只在末尾加 1 个 `if` 分支 |
| `fliki-clone-api/requirements.txt` | 加 `reportlab>=4.0` | 既有依赖版本未改 |
| `fliki-clone-api/.env.example` | 追加 SMTP_\* + INVOICE_EMAIL_ENABLED 段（含示例 + 说明） | 既有 STRIPE_\* 段未改 |

**严格独占**：alembic 没动；既有 router / 前端 / pipeline / publishing 模块零改动。

## 2. 关键设计

1. **主开关 `invoice_email_enabled`（缺省 False）**
   - 本地 dev / 测试默认不真发，避免误打扰真实用户
   - 关闭时 handler 直接 short-circuit 返 `{handled:True, sent:False, reason:"invoice_email_enabled=false"}`
   - **stripe 不重投**（webhook 200）：避免没配 SMTP 的环境被同一事件反复回调

2. **三层 fail-safe，全部翻 `sent:False`**：
   - 开关关 → `reason="invoice_email_enabled=false"`
   - SMTP 缺配置 → `EmailNotConfigured` 捕获 → `reason="smtp not configured"`
   - PDF 渲失败 / SMTP 投递失败 → 异常捕获 → `reason="pdf render failed: ..."` / `reason="smtp send failed: ..."`
   - 设计哲学：**任何情况下都不让 stripe 把 invoice.paid 反复重投打满 worker**；想补发用 stripe dashboard 重发 webhook 即可

3. **数据源**：
   - PDF stripe lines：从 `invoice.lines.data` 直接折算 cents → USD（一行一行喂 `StripeInvoiceLine`）
   - PDF provider 拆分：本周期内 `model_calls` 表按 `tenant_id + created_at ∈ [period_start, period_end)` GROUP BY provider；用了 T-18 落库的 `model_calls.tenant_id` 索引列；DB 失败时返空集，让 PDF 至少能渲订阅费部分
   - tenant 解析：`pipeline.tenant.resolve_tenant_context(user_id, user_plan=plan)`，与 webhook 其他 handler / cost.py 一致（`ws:{workspace_id}` > `u:{user_id}`）

4. **user 解析优先级**：`metadata.user_id` > `_user_id_for_sub(sub_id)` > `_user_id_for_customer(customer_id)`；都解析不到返 `sent:False, reason="user not resolved from invoice"`

5. **SMTP 模式**：根据 `smtp_use_ssl` / `smtp_use_tls` 选 `SMTP_SSL` / `SMTP+STARTTLS` / 明文；用 stdlib `email.message.EmailMessage` 拼 RFC 5322 + 自动 base64 附件；不依赖 `MIMEMultipart`（避免 Gmail 中文标题编码 bug）

6. **PDF 视觉**：
   - 文字 logo「Fliki」emerald-700（与前端 cost panel 同色系）
   - 双栏 header：左 plan/tenant/bill-to 用户信息；右 invoice 编号 + Stripe ID + period + currency
   - 两张表（Subscription charges / Compute usage by provider），每张带 subtotal 行；header 浅 emerald 背景，斑马纹行
   - 右下角 Total 行：subscription 费 + compute 费汇总；备注「compute 仅展示，不另外计费」
   - 接入真 logo 图片只需把 `_render_header` 的 `Paragraph("Fliki", styles["LogoTitle"])` 换成 `Image(path)`

## 3. 烟测

```bash
cd /Users/zhaoguangyuan/project/empty-track22/fliki-clone-api
/Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest -v
```

结果（2026-05-05 完成时）：

```
======================== 96 passed in 2.30s =========================
tests/test_admin_flags.py .......                          [  7%]
tests/test_art_v3.py ........                              [ 15%]
tests/test_billing_webhook.py ......                       [ 21%]   ← Track-16 webhook 6 case 全部 PASS（dispatch 入口未破坏）
tests/test_canary_multichar_combo.py ....                  [ 26%]
tests/test_dlq_retry_publish.py .......                    [ 33%]
tests/test_publishing.py ........                          [ 41%]
tests/test_quota_v2.py ........                            [ 50%]
tests/test_track09_multichar.py ......                     [ 56%]
tests/test_track17_sse_resume.py ..........                [ 66%]
tests/test_track18_cost.py ..........                      [ 77%]
tests/test_track22_invoice_email.py .......                [ 84%]   ← 新增 7 case
tests/test_voice_v4.py .......                             [ 91%]
tests/test_youtube_chunked_upload.py ........              [100%]
```

新 case 覆盖：

1. `test_render_invoice_pdf_returns_valid_pdf_bytes` — bytes 非空 + `%PDF-` 头 + `%%EOF`
2. `test_render_invoice_pdf_includes_invoice_id_in_metadata_and_filename` — `/Title` 元数据 + `build_filename` 结构
3. `test_smtp_send_raises_email_not_configured_when_host_missing` — 缺配置抛
4. `test_handle_invoice_paid_skipped_when_email_disabled` — 开关关分支（unit）
5. `test_handle_invoice_paid_skipped_when_smtp_not_configured` — SMTP 缺分支（integration，真 PG seed user + sub）
6. `test_handle_invoice_paid_calls_send_email_when_fully_configured` — 真发分支（integration，monkeypatch send_email + 验证 PDF 附件 / to / subject / body 关键词）
7. `test_handle_invoice_paid_skipped_when_user_email_missing` — user.email 空字符串场景（integration）

### 3.1 真发本地端到端（可选）

依赖外部环境（mailpit 或 smtp4dev），未跑：

```bash
docker run -p 1025:1025 -p 8025:8025 axllent/mailpit
# .env 加：
#   SMTP_HOST=localhost
#   SMTP_PORT=1025
#   SMTP_USER=anything
#   SMTP_PASSWORD=anything
#   SMTP_USE_TLS=false
#   SMTP_USE_SSL=false
#   INVOICE_EMAIL_ENABLED=true
# 重启 backend
stripe trigger invoice.paid
# 浏览器 http://localhost:8025 看收件箱
```

## 4. 已知边界 / 跳过的子任务

1. **不发 HTML 邮件**：纯文本 + PDF 附件够覆盖月账单场景；HTML 留给 follow-up
2. **不做月度跨期 cron**：v1 仅在 stripe 真触发 `invoice.paid` 时发；自然月底 stripe 自带 dunning 会触发
3. **不写 `subscriptions.last_invoice_url` 字段**：卡片里写「如果有需要也行可不需要」，没加；现表 schema 没这列，避免引 alembic 改动
4. **PDF 没接真 logo 图片**：用文字代替（reportlab `Paragraph`）；接入真 logo 只需把 `invoice_pdf._render_header` 那一行替换为 `Image("path/to/logo.png", width=..., height=...)`
5. **不重试 SMTP**：smtplib 抛异常直接 catch + 返 sent:False；让 stripe 不重投（重试由 stripe dashboard 手工触发）
6. **PDF 渲染调用方需要先安装 reportlab**：`requirements.txt` 已加；本次 venv 是手工 `python -m pip install`（venv 的 pip shebang 指向旧路径，必须用 `python -m pip` 才能装到正确 site-packages，避免后续合并踩坑）
7. **SMTP 与既有 `mail_*` 字段并存**：`mail_*` 是 fastapi-mail 的历史遗留（用户注册验证邮件用），本 Track 用 stdlib `smtplib` 走 `smtp_*` 命名空间，互不影响；将来若要统一可由 follow-up 处理
8. **provider_breakdown 里 cost_usd 直接来自 model_calls 表**：T-18 的成本视图保证了「按 tenant 准确聚合」；但 stripe lines 用的是订阅费，与 model_calls 算力费不冲突 —— PDF 上 Total = stripe lines 之和 + model_calls 之和，**只是展示分项**；真实 stripe 收款金额仍是 stripe 那一份（`amount_paid`），compute 部分备注里说明仅供透明用途

## 5. Follow-up 建议（不在本 Track 范围）

1. **HTML 邮件模板**：用 jinja2 渲染 + 双 part（plain/HTML）
2. **invoice 历史 / 按月 cron 重发**：在 admin 后台加「resend invoice for invoice_id」按钮
3. **统一 mail_\* 与 smtp_\* 命名空间**：fastapi-mail 改用 stdlib smtplib 后可移除 fastapi-mail 依赖
4. **真 logo 接入**：放一份 SVG/PNG 到 `app/services/billing/assets/`，header 渲染换 `Image`
5. **subscriptions.last_invoice_pdf_url 列**：把 PDF 上传到 S3 留 URL，邮件里附 link 而非附件（绕过 25MB 邮件附件限制）
6. **送达回执**：接 SES bounce/complaint webhook，subscriptions 行加 `last_invoice_email_status` 字段
7. **接入 OAuth2 (XOAUTH2) SMTP relay**：当前只支持密码登录；Gmail / Outlook 推 OAuth 后这层要扩

## 6. 与其他 Track 的协调注意事项

- **T-23 共享 `app/config.py`**：本 Track 仅加 SMTP_\* / invoice_email_enabled 字段（位于 Stripe 段之后、Publishing Fernet 段之前）；T-23 加 `admin_emails` 字段时按协调者顺序合（T-22 先 → T-23 后），手解时 T-23 拿到 main 后 rebase 即可，无需冲突
- **T-21 不冲突**：T-21 只动 `routers/cost.py`（加 `/timeseries` 段）+ 前端 admin metrics；不与本 Track 任何文件重叠
- **不动 alembic / 不动既有 router**：第五波本批 T-22 不占用迁移槽（C3D4E5F6A7B8 仍是 head）
