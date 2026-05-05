# Track-18 · model_calls 加 tenant_id + 按 tenant 聚合 cost 视图

> 分支：`track-18-model-calls-tenant`（worktree：`/Users/zhaoguangyuan/project/empty-track18`）
> 基线：`main` @ `3b05011`（第三波合并交接）
> alembic head：`b2c3d4e5f6a7` → **`c3d4e5f6a7b8`**（独占第四波本批迁移槽）

## 目标完成

1. **model_calls 按 tenant 聚合**：加 `tenant_id` 列 + 索引 + 一次性 backfill 老行为 `u:{user_id}` 命名空间
2. **gateway.record_call 透传 tenant_id**：来自 `RenderRequest.tenant_id`，缺失时兜底 `u:{user_id}`
3. **新 cost 路由** `/api/cost/summary` + `/api/cost/recent`：按 tenant 聚合 + provider 拆分 + 最近 N 条明细
4. **前端 cost panel**：4 格 stat 下方折叠 details，按 provider 横向 bar（emerald=OpenAI / sky=SiliconFlow / amber=Kling / violet=ElevenLabs / slate=local）

## 改的文件 + 为什么

| 文件 | why |
|---|---|
| **新** `fliki-clone-api/alembic/versions/20260505_1600_add_model_calls_tenant_id.py` | rev `c3d4e5f6a7b8` 顶 `b2c3d4e5f6a7`；加 `model_calls.tenant_id VARCHAR(200) NULL` + 普通索引 `ix_model_calls_tenant_id`；一次性 backfill：`UPDATE model_calls SET tenant_id = COALESCE('u:' || user_id, 'anon:default') WHERE tenant_id IS NULL`。downgrade 走 `drop_index + drop_column` 双向无副作用 |
| `fliki-clone-api/app/models/model_call.py` | ORM 加 `tenant_id: Mapped[Optional[str]]`；带 index=True 与 alembic 一致；只反映 schema 变化，业务读写仍走同步 SQL |
| `fliki-clone-api/app/services/model_gateway/cost.py` | (1) 新加 `_resolve_tenant_for_record(explicit, user_id)` 公共判定（`explicit` > `u:{user_id}` > None）；(2) `record_call` 加 `tenant_id` kwarg，INSERT 多写一列；(3) 与 `pipeline.tenant.resolve_tenant_id` 兜底约定保持一致（`ws:` 由调用方塞，user 级 `u:`，匿名 None 让 DB NULL） |
| `fliki-clone-api/app/services/model_gateway/gateway.py` | `_record(request, result)` 调 `record_call` 时多传 `tenant_id=request.tenant_id`，让记账与配额 v2 同维度（gateway 入口已经做过 user_id → tenant 兜底，request.tenant_id 此时已是有效值；缺失时 cost 层再兜一次 `u:{user_id}` 双重保险）|
| **新** `fliki-clone-api/app/routers/cost.py` | 2 端点 + 安全 helper `_resolve_query_tenant`：未传 tenant_id 走 user 自己；传了但与 user 自己 tenant 不同 → 仅 admin 直通，否则**静默覆盖回自己**（不抛 403，避免破坏 admin 从前端抛参数的体验）。`/summary` 按 provider 聚合（`SUM(cost_usd)` + `COUNT` + `success_count` / `failed_count`）；`/recent` 按 created_at DESC + limit。period 三档 `monthly`（本自然月）/ `weekly`（最近 7d）/ `daily`（最近 24h）|
| `fliki-clone-api/app/routers/__init__.py` | 导出 `cost_router` |
| `fliki-clone-api/app/main.py` | `include_router(cost_router, prefix=PREFIX)` |
| **新** `fliki-clone/src/lib/cost.ts` | TS 类型 `CostPeriod` / `ProviderCostRow` / `CostSummary` / `RecentCall`；fetch helper `getCostSummary` + `getRecentCostCalls` |
| `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx` | (1) 加 `costSummary` state；(2) `refreshQuota` 同步拉 `getCostSummary({period:"monthly"})`（与 quota 同生命周期，run 终态 +1 自动刷新）；(3) 新 `<CostBreakdownPanel>` 子组件挂在 provider buckets details 之后，折叠 details 默认收起；最大 provider 占 100% 视觉宽度，hover 显示「成功 N · 失败 M」；(4) `providerTone(provider)` 颜色映射函数 |
| **新** `fliki-clone-api/tests/test_track18_cost.py` | 10 case：4 unit（resolve_tenant 三分支 + period_window 三模式）+ 6 integration（record_call 写 tenant_id 双路径 / 匿名 NULL / summary 聚合 / period 边界过滤 / recent DESC + limit / admin 鉴权穿透）|

## 烟测

```bash
cd /Users/zhaoguangyuan/project/empty-track18/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m alembic upgrade head
# → Running upgrade b2c3d4e5f6a7 -> c3d4e5f6a7b8, add_model_calls_tenant_id

# alembic 双向回测（不会丢数据，downgrade 只是 drop column）
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic upgrade head

# 跑测
.venv/bin/python -m pytest tests/test_track18_cost.py -v
# → 10 passed

# 全量回归
.venv/bin/python -m pytest -q
# → 89 passed in 2.06s（基线 79 + 本 Track 10，零回归）

# 路由 sanity
.venv/bin/python -c "from app.main import app; print(len(app.routes))"
# → 120
.venv/bin/python -c "
from app.main import app
[print(r.methods, r.path) for r in app.routes if 'cost' in r.path]
"
# → {'GET'} /api/cost/summary
# → {'GET'} /api/cost/recent
```

未跑：
- 真启 backend + 浏览器观察 cost panel 横向 bar 渲染（agent 没起服务；hot-reload 自动生效）
- 跑一次 video_full 端到端验证 record_call 链路（依赖外网真发，由协调者本机 e2e）

## 互斥锁守住

- ✅ alembic 槽 rev `c3d4e5f6a7b8`（独占；与既有 `b2c3d4e5f6a7` 串行无冲突）
- ✅ 不动 `.env` / `app/config.py`（既有配置项已就绪）
- ✅ 不动 `routers/admin_flags.py` / `routers/dlq.py` / `routers/billing.py` / `routers/production.py` 等其它路由（只引用 `_is_admin_email`，不修改）
- ✅ 不动 `services/pipeline/*`（只 import `tenant.resolve_tenant_id` 不改）
- ✅ `pipeline/page.tsx` 只动 4 格 stat 下方的 cost panel 段（provider buckets details 之后）+ refreshQuota；不动 PlanRow / EditArtifact / ArtArtifact / VideoArtifact 等其它 panel

## 已知边界 / 设计取舍

1. **不强制 admin**：未传 `?tenant_id=` 走自己；传了非自己的 → 仅 admin 直通，**非 admin 静默覆盖回自己**（不抛 403）。这样 admin 从前端 query 抛 `?tenant_id=ws:xxx` 不影响普通用户—— 普通用户访问就是看自己。
2. **总额可能与 quota.usage 不严格相等**：quota 是 run 级 reserve+settle 累计；cost 是 model_call 粒度。差额来自 `partial_failed` 不退还的 reserved 漂移（v1 设计），以及 `record_call` 写库失败 `warning` 兜底（极少）。前端横条仅作明细参考，权威成本以 quota.usage 为准。
3. **不做时序聚合**：v1 cost 视图不按天/小时滚动；L-03 `metric dashboard` 才做时序（届时直接消费 model_calls 已写入的 tenant_id 列）。
4. **不加复合索引**：`(tenant_id, created_at)` 或 `(tenant_id, provider)` 等待真出现慢查询再加；v1 简单 idx + period range scan 已够（PG 自动用索引选择性最佳的列）。
5. **provider 颜色映射写死**：emerald=OpenAI / sky=SiliconFlow / amber=Kling / violet=ElevenLabs / slate=local。后续接新 provider 在 `providerTone` 加分支即可。
6. **测试边界 case**：`test_cost_summary_period_filter_excludes_old_rows` 用 60 天前的「老行」做兜底（避开月初当天跑测试时把 1 天前误算入本月的边界），保证 monthly 永远过滤掉 far_old 行。

## Follow-up

- [ ] **L-03 metric dashboard 升级**：基于本 Track 已写入的 tenant_id 做按天/按 provider 时序图（现成的 Cost API 拓展时间窗参数即可）。
- [ ] **`/cost/recent` 加 user_id 过滤**：当前同 tenant 内全部 user 调用合一展示；workspace 多人协作时可能想看「哪个 user 烧得最多」，加 `?user_id=` 即可（admin 限定）。
- [ ] **前端 cost panel 加切换按钮**：让用户在 monthly / weekly / daily 间切；当前固定 monthly。
- [ ] **L-13 `ADMIN_EMAILS` 迁回 Settings**：本 Track 的 `_resolve_query_tenant` 通过 `_is_admin_email` 间接读 env，与 Track-10/14 一致；Track-01 互斥锁早已解除，可以做了。
- [ ] **/cost/summary 加 cache**：刷新频次可能比较高（每次 quota refresh 都拉一次），如果用户 model_calls 量大（每个 video_full 跑 10-30 次记账）后续可加 60s 内存 cache。
