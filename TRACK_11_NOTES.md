# Track-11 · Stripe 计费对接 — 完成记录

> 分支：`track-11-stripe-billing`
> 提交：见本分支 `git log --oneline track-11-stripe-billing ^main`
> alembic head 不变（**不动 schema**）：复用现有 `subscriptions` /
> `tenant_quotas` / `provider_concurrency_buckets` 三张表

## 1. 改了哪些文件 + 为什么

### 后端

| 文件 | 改动 | 为什么 |
|---|---|---|
| **新** `app/services/billing/__init__.py` | 模块导出 | 把 stripe 胶水从 router 抽到 service 层 |
| **新** `app/services/billing/stripe_client.py` | 薄封装 stripe SDK：`init_stripe / create_checkout_session / create_portal_session / verify_webhook_event / plan_for_price_id` | router / handler 不感知 stripe 内部对象；缺 secret 抛 `StripeNotConfigured` 让 router 翻 503 而不是裸 500 |
| **新** `app/services/billing/webhook_handlers.py` | 派发 4 个事件 → DB | 真正落库 + 触发 tenant_sync。事件矩阵：`checkout.session.completed` / `customer.subscription.{updated,deleted}` / `invoice.payment_failed` |
| **新** `app/services/billing/tenant_sync.py` | `sync_user_plan(user_id, new_plan)` | user 维度 plan 切换 → 解析 tenant_id（沿用 `pipeline.tenant.resolve_tenant_id`）→ 调 quota 同步；匿名 / 空 user_id 走 skipped 不阻塞 webhook |
| `app/services/pipeline/quota.py` | 加 `update_tenant_plan(tenant_id, new_plan)` 函数 | UPDATE `tenant_quotas.plan` + bump `monthly_limit_usd` / `concurrent_max`（升级取 `PLAN_DEFAULTS` 大值；降级保留运维手调过的值），遍历该 tenant 已存在的 `provider_concurrency_buckets` 调 `ensure_bucket(plan=new)` 自动 bump per-provider max_concurrent |
| `app/routers/billing.py` | 整体重写 | v1 只更新 `User.plan + credits_total`，跳过 v2 配额。新版： `GET /billing/plan`（含 tenant snapshot）、`POST /billing/checkout-session`、`POST /billing/portal-session`、`POST /billing/webhook`；保留 `/billing/checkout` + `/billing/portal` 兼容旧 mock |
| `app/config.py` | 加 `stripe_price_free: str = ""` | free 档目前不真扣款；保留字段方便未来「free 也走 Checkout 拿 customer」 |
| `app/schemas/__init__.py` | `CheckoutRequest.success_url/cancel_url` 改 `Optional[str] = None` | 前端不传时 router 用 `settings.frontend_url + /app/billing` 兜底；调用方更省事 |
| `.env.example` | 新建：`STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PRICE_FREE` / `STRIPE_PRICE_STANDARD` / `STRIPE_PRICE_PREMIUM` | 新部署人能看到该配什么 |

### 前端

| 文件 | 改动 | 为什么 |
|---|---|---|
| **新** `fliki-clone/src/app/[locale]/(app)/app/billing/page.tsx` | 真实订阅页 | 调真后端 `GET /api/billing/plan` 拿当前 plan + tenant 配额；3 栏 plan 卡片，点「升级」跳 Checkout、点「管理订阅」跳 Customer Portal；监听 `?session_id` 跳回参数 1.5s 后 refetch（webhook 处理完再刷 tenant 视图）|

旧 `fliki-clone/src/app/[locale]/(app)/settings/billing/page.tsx`（mock UI）**保留不动**——避免影响其他 panel；用户后续可以在 settings layout 加链接跳到 `/app/billing` 或直接弃用旧页。

## 2. 互斥锁遵守

- ✅ **不动 alembic**（schema 完全不变）
- ✅ **不动 publishing/adapters**
- ✅ **不动 pipeline/page.tsx 等其他 panel**
- ✅ Track-11 卡片要求的 5 类文件全部独立持有

## 3. 烟测

### 3.1 后端 import + 路由注册

```bash
cd fliki-clone-api && .venv/bin/python -c "
from app.main import app
print('routes:', sum(1 for r in app.routes if 'billing' in getattr(r, 'path', '')))
for r in app.routes:
    if 'billing' in getattr(r, 'path', ''):
        print(' ', getattr(r, 'methods', '?'), r.path)
"
```

预期输出（已验证）：

```
routes: 6
  {'GET'} /api/billing/plan
  {'POST'} /api/billing/checkout-session
  {'POST'} /api/billing/checkout         (legacy, hidden in schema)
  {'POST'} /api/billing/portal-session
  {'POST'} /api/billing/portal           (legacy, hidden in schema)
  {'POST'} /api/billing/webhook
```

### 3.2 webhook handler dispatch（无 DB 也能跑）

```bash
.venv/bin/python -c "
from app.services.billing.webhook_handlers import handle_webhook_event

# missing user_id 走 ignore 分支
r = handle_webhook_event({
    'id': 'evt_test_unknown',
    'type': 'checkout.session.completed',
    'data': {'object': {'metadata': {}}},
})
assert r['handled'] is False, r
print('ignore branch OK')

# unknown event 也是 ignore
r = handle_webhook_event({'id': 'evt_x', 'type': 'price.updated', 'data': {'object': {}}})
assert r['handled'] is False, r
print('unknown event OK')

from app.services.billing.tenant_sync import sync_user_plan
r = sync_user_plan('', 'standard')
assert r.skipped_reason == 'empty user_id', r
print('empty user_id OK')
"
```

### 3.3 Stripe CLI 真实联调（需要本机起 backend + Stripe CLI）

```bash
# 1) 终端 A：起 backend（按 SESSION_HANDOFF 的命令，**不带 --reload**）
cd fliki-clone-api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 终端 B：让 Stripe CLI 把 webhook 转发到本地
stripe listen --forward-to http://127.0.0.1:8000/api/billing/webhook
# → 会打印 webhook signing secret，复制到 .env 的 STRIPE_WEBHOOK_SECRET 然后重启 backend

# 3) 终端 C：触发一次 checkout.session.completed（带 user_id metadata）
stripe trigger checkout.session.completed \
  --add 'checkout_session:metadata[user_id]=<你的真实 demo user uuid>' \
  --add 'checkout_session:metadata[plan]=standard'

# 4) 看 backend 日志：应该输出
#    "billing checkout completed event=evt_… user=… plan=standard sub=sub_… tenant=u:…"
#    "tenant plan updated tenant=u:… plan=standard monthly_limit_usd=100.0 concurrent_max=5 …"

# 5) 直接查 PG
psql fliki -c "SELECT plan, monthly_limit_usd, concurrent_max FROM tenant_quotas WHERE tenant_id='u:<demo-user-uuid>';"
# 期望：plan=standard, monthly_limit_usd=100.0, concurrent_max=5

psql fliki -c "SELECT plan, status, stripe_customer_id, stripe_sub_id FROM subscriptions WHERE user_id='<demo-user-uuid>';"
# 期望：plan=standard, status=active
```

### 3.4 真实 Checkout（test mode 4242 卡）

```bash
# 1) 在 .env 配真实 sk_test_* + 真实 price_*（standard / premium）
# 2) 前端访问 http://localhost:3000/app/billing
# 3) 点 "Upgrade to Standard" → 跳到 Stripe 托管 Checkout
# 4) 卡号 4242 4242 4242 4242 / 任意未来日期 / 任意 CVC / 任意邮编
# 5) 支付成功 → 自动跳回 /app/billing?session_id=cs_test_*
# 6) webhook 触发 → tenant_quotas.plan=standard, monthly_limit_usd=100, concurrent_max=5
# 7) 前端 1.5s 后 refetch → 看到 Active 徽章 + $100 月度额度 + 并发 5
```

## 4. 已知边界 / 跳过的子任务

1. **退款不退还配额**：`charge.refunded` 事件未处理；用户退款后仍保留当月配额到自然月末，避免误杀正常用户；后续可加 ops 工具人手回滚
2. **降级延迟生效**：webhook 收到 `customer.subscription.deleted` 后立刻把 tenant 切回 free；如果用户在 stripe portal 里只是「取消下次续费」，stripe 会等 period 末才发 deleted，期间 user 仍享有付费档（行为正确）
3. **monthly_limit_usd 降级保护**：`update_tenant_plan` 降级时**不下调** `monthly_limit_usd / concurrent_max`，保留运维 / 用户手调过的值。即「standard → free」并不会立刻把额度从 $100 砍到 $10；这是个有意设计的语义（保护误降；下个月跨月 rollover 时仍按现有行的 limit 算）。如果产品同学希望「降级即降额」，把 `update_tenant_plan` 里 `new_limit = max(...)` 改成无条件用 `desired_*` 即可
4. **未做 stripe.Customer 主动建档**：v1 只在 checkout.session 完成后才有 customer_id；free 用户没 customer_id 就**没法**从前端跳到 portal（按钮在 free 档下隐藏）。后续可以在用户注册时就 `stripe.Customer.create` 拿 id，但需要存在 `users.stripe_customer_id` 列（要 alembic）
5. **未发邮件通知**：升级 / 降级成功只写日志；后续接 fastapi-mail / Resend 发收据
6. **stripe SDK 版本**：当前 requirements.txt 锁 `stripe==11.4.0`，与本 Track 兼容
7. **Track-11 卡片说"GET /billing/plan 兼容旧前端 mock"**：旧 `/settings/billing/page.tsx` 仍是纯 mock 没调任何 API，所以本 Track 没改它；新前端在 `/app/billing` 是独立路由

## 5. Follow-up（建议）

- [ ] **L-04 月账单 PDF 导出 + 邮件**（长尾任务）：拿 stripe `invoice.paid` 事件 + 渲染 PDF
- [ ] **/app/billing 入口可见性**：在 AppShell 侧栏 / 用户头像菜单加「Billing」入口（目前用户必须手动输 URL 才能到达）
- [ ] **退订前确认对话框**：当前 portal 跳转直接进 stripe，可以在前端拦一层「降级会失去的功能列表」
- [ ] **subscriptions.stripe_customer_id 升级到 users 表**：减少多次 join；下一个 alembic 迁移槽可以做
- [ ] **handler 单元测试**：模拟 stripe Event payload 跑 `handle_webhook_event`，断言 DB 变化（Track-08 pytest 已建好骨架，跟进时加 `tests/test_billing_webhook.py`）

## 6. 协调者合并提示

- 合并 Track-11 后：
  1. 重启 backend（按 SESSION_HANDOFF 的命令，**不带 `--reload`**）
  2. 前端 hot-reload 自动生效；浏览器访问 http://localhost:3000/app/billing
  3. 在 `.env` 配真实 STRIPE_* 后才能跑真 Checkout；不配也能加载页面（GET /billing/plan 仍工作，只是按 free 显示，点升级按钮会拿到 503 提示「STRIPE_SECRET_KEY 未配置」）
- 合并完写 SESSION_HANDOFF.md 时，建议在「能力清单」表加一行：
  ```
  | Stripe 计费 v2 + tenant_quotas 同步 | ✅ | webhook 把 plan 同步到 tenant_quotas + bump provider_concurrency_buckets；前端 /app/billing 三栏卡片 |
  ```
- alembic head 仍是 `9c2d4e5f6a7b`（Track-11 没碰 schema）
