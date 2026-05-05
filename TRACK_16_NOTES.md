# Track-16 · Stripe webhook 单元测试 + 退款事件

> 分支：`track-16-stripe-webhook-tests`（worktree：`/Users/zhaoguangyuan/project/empty-track16`）
> 基线：`main` @ `68fccd3`（第三波 Backlog 合并后）
> alembic：从 `a1b2c3d4e5f6` → **新 head `b2c3d4e5f6a7`**（占第三波本批迁移槽，独占）

## 目标完成

1. **退款事件 `charge.refunded` 接入**：webhook 触发时把 `subscriptions.refunded_at`
   打成 NOW，**不动** `tenant_quotas` / `users.plan` / `subscriptions.plan`，
   保留当月已用配额到自然月末（v1 用户体验优先；ops 评估后人手降级）。
2. **6 个 case 端到端单元测试**：补齐 Track-11 webhook handler 的回归保护，覆盖
   全部 5 类支持事件 + 1 类未知事件。

## 改的文件 + 为什么

| 文件 | why |
|---|---|
| `fliki-clone-api/alembic/versions/20260505_1500_add_subscription_refunded_at.py` | 新 alembic rev `b2c3d4e5f6a7`，顶 `a1b2c3d4e5f6`；加 `subscriptions.refunded_at TIMESTAMPTZ NULL`。**不**加 server_default（避免老行误打标），**不**加索引（退款查询频次极低）。downgrade 走 `drop_column` 无副作用。 |
| `fliki-clone-api/app/models/billing.py` | `Subscription` ORM 加 `refunded_at: Mapped[Optional[datetime]]`，`nullable=True`；只是反映 schema 变化，业务读写仍走 sync engine（与 quota.py 一致），ORM 仅用于 metadata.create_all 与开发期 IDE 提示。 |
| `fliki-clone-api/app/services/billing/webhook_handlers.py` | (1) docstring 事件矩阵补 `charge.refunded` 行 + 设计取舍说明；(2) `handle_webhook_event` dispatch 加 `if event_type == "charge.refunded"` 分支；(3) 新 `_handle_charge_refunded(charge, *, event_id)`：解析订阅优先级为 `metadata.subscription_id` → `customer` 反查最新一条订阅；都不命中返 `{handled: True, matched: 0, reason: ...}` 让 stripe 不重投；(4) 两个 helper：`_mark_subscription_refunded_by_sub_id` / `_mark_latest_subscription_refunded_by_customer`（按 customer 找最新一条）。 |
| `fliki-clone-api/tests/test_billing_webhook.py`（新文件）| 6 个端到端 case，使用 conftest `temp_user` + 自有 `billing_user` fixture（带 tenant_quotas seed + teardown）。`make_event(...)` 工厂私有于本文件，**不污染 conftest**（与 Track-08 工程化原则一致）。一个非 DB 的 `test_unknown_event_returns_handled_false` 标 `unit`，其他 5 个标 `integration`。|

互斥锁守住：
- alembic 槽 ✅（rev `b2c3d4e5f6a7`，顶 `a1b2c3d4e5f6`）
- `models/billing.py::Subscription` 加列 ✅（与 Track-11 不重叠）
- `services/billing/webhook_handlers.py` 加新 handler 函数 ✅（不动既有 4 handler）
- 新 `tests/test_billing_webhook.py` ✅（独占文件名）

未触碰的文件（按通用规则 §3-§5）：
- `.env` / `app/config.py`（既有 `STRIPE_*` 已就绪）
- `pipeline/page.tsx` / `use-publish-plan-stream.ts` / `use-pipeline-stream.ts`
- 第三波其他 Track 占用的文件（Track-13 youtube adapter / Track-14 admin / Track-15 dlq / Track-17 events.py）

## 烟测结果

```bash
# 1. 新 case 单跑
$ cd /Users/zhaoguangyuan/project/empty-track16/fliki-clone-api && \
    /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest tests/test_billing_webhook.py -v
...
tests/test_billing_webhook.py::test_checkout_session_completed_inserts_subscription_and_syncs_quota PASSED
tests/test_billing_webhook.py::test_subscription_updated_switches_plan_and_bumps_quota PASSED
tests/test_billing_webhook.py::test_subscription_deleted_marks_canceled_and_drops_user_to_free PASSED
tests/test_billing_webhook.py::test_invoice_payment_failed_sets_past_due_only PASSED
tests/test_billing_webhook.py::test_charge_refunded_marks_refunded_at_without_touching_quota PASSED
tests/test_billing_webhook.py::test_unknown_event_returns_handled_false PASSED
============================== 6 passed in 0.87s ===============================

# 2. 全套零回归（基线 41 → 47）
$ pytest -q
...............................................                          [100%]
47 passed in 1.20s

# 3. alembic 来回测
$ alembic current   → b2c3d4e5f6a7 (head)
$ alembic downgrade -1   → b2c3d4e5f6a7 → a1b2c3d4e5f6
$ alembic upgrade head   → a1b2c3d4e5f6 → b2c3d4e5f6a7
$ alembic current   → b2c3d4e5f6a7 (head)
# information_schema.columns 验证：refunded_at 列在 subscriptions 表上存在
```

**注**：下一波 agent 启动前需 `alembic upgrade head` 一次（人类合并 Track-16 后即可）。

## 已知边界 / 跳过的子任务

1. **`charge.refunded` 解析订阅的 fallback**：
   - 卡片原文 `WHERE stripe_charge_id = event.data.object.id`，但现 `subscriptions`
     表没有 `stripe_charge_id` 列（Track-11 没引；要引会牵动 invoice.paid 事件
     去 backfill）。
   - 实际实现：优先 `charge.metadata.subscription_id`（ops 手动 trigger 可指定），
     fallback `charge.customer` 反查最新一条订阅；单订阅用户 100% 命中。
   - 多订阅用户（同 customer 多个并存的 subscription）会命中**最新创建那条**；
     这是 v1 妥协，正式方案见 follow-up §1。
2. **不在 webhook 里发 stripe 出站调用反查 invoice → subscription**：避免 stripe
   不可达把 webhook 回 5xx，stripe 重投把 worker 打满。
3. **`charge.refunded` 不动 `tenant_quotas`** 是产品取舍，不是 bug：当月已用配额
   对应的真实成本无法追回（已付 OpenAI / SiliconFlow），强制清零会让用户当月已起
   的 run 中途挂掉。
4. **新 case 需要 PG**：5 个标 `integration`，CI runner 没装 PG 会自动 skip
   （走 conftest 的 `pg_engine` fixture）。本机有 PG 直接 PASS。
5. **没改前端**：本 Track 完全后端范围；前端 admin 退款打标 UI 留给 Track-14 的
   后续迭代（Track-14 当前只做 feature flags 面板）。

## Follow-up（不在本 Track 内）

1. **正式 charge → subscription 映射**（建议跟 L-04 月账单一起做）：
   - 给 `subscriptions` 加 `stripe_latest_charge_id` 列（或新 `subscription_charges`
     映射表，存 `charge_id`/`invoice_id`/`subscription_id`/`paid_at`）
   - 在 `invoice.paid` / `payment_intent.succeeded` 事件里 backfill
   - 这样 `charge.refunded` 可以精准定位单笔退款对应的订阅（多订阅用户也对）。
2. **跨月 cron 自动降级**：refund 后到下个 `tenant_quotas.current_period_start`
   时检查 `refunded_at < period_start` → 自动 `update_tenant_plan(tenant_id, 'free')`，
   避免 ops 漏处理用户继续白嫖大额度。
3. **退款邮件通知**（依赖 fastapi-mail / Resend，与 Track-11 follow-up 一起做）。
4. **router 层接入**：当前 `app/routers/billing.py::stripe_webhook` 已经把所有
   验签后的 event 转给 `handle_webhook_event`，新事件类型自动生效；但建议人类合并
   后跑一次 `stripe trigger charge.refunded` 真烟测确认 router 链路也 OK
   （需要 `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET` 真值）。
5. **`subscriptions` 表的 `refunded_at` 索引**：当前没建；如果未来 ops 需要
   「列所有近 7 天退款的订阅」高频查询，再补 `CREATE INDEX ... WHERE refunded_at IS NOT NULL`
   部分索引。

## 给协调者（人类）的合并 checklist

1. `git checkout main && git merge --no-ff track-16-stripe-webhook-tests`
2. `cd fliki-clone-api && .venv/bin/python -m alembic upgrade head` → `b2c3d4e5f6a7`
3. `cd fliki-clone-api && make test` → 应得 **47 passed**
4. （可选真烟测）配 `.env` 的 `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`，
   `stripe listen --forward-to localhost:8000/api/billing/webhook`，
   `stripe trigger charge.refunded` → 看后端日志 `billing charge.refunded matched`
   + DB `subscriptions.refunded_at` 写入。
5. 删 `TRACK_16_NOTES.md` 合并到 `SESSION_HANDOFF.md` 第 0.x 节（Track-16 行）。
6. 更新 `SESSION_HANDOFF.md` 的 alembic head 到 `b2c3d4e5f6a7`。
7. 删 worktree：`git worktree remove ../empty-track16` + `git branch -d track-16-stripe-webhook-tests`。
