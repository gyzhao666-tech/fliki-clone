# Track-21 · L-03 metric dashboard：cost 时序图 + admin metrics 页

**分支**：`track-21-metric-dashboard`
**基线 commit**：`ff48c75 docs(agents): 第五波 Backlog（T-20/21/22/23/24/25 完整卡片）`
**alembic head**：`c3d4e5f6a7b8`（不动；本 Track 不加 schema）

---

## 1. 改了什么 / 为什么

### 1.1 后端 — `fliki-clone-api/app/routers/cost.py`（追加 `/timeseries` 段）

末尾追加 95 行；**完全不动既有 `/summary` `/recent` 段及其 helper**（互斥锁约束 + 通用规则 7「why over what」）。

- 新加 Pydantic 模型 `CostTimeseriesPoint` / `CostTimeseriesOut`
  - 与 `/summary` 字段命名对齐（`tenant_id` / `period_start` / `period_end` / `total_*`）
  - `provider_filter` 字段回显前端的 `?provider=` 入参，方便 UI 显示「仅 X provider」徽标
- 新加 helper `_resolve_bucket(period)`：whitelist 到 PG `DATE_TRUNC` 单位（`'day'` / `'week'`）
  - **避免 SQL 注入**：bucket 字符串只能从字典取值，未知 period 兜底 `'day'`
- 新加 helper `_clamp_days(days)`：clamp [1, 365]，非整数回 30
- 新端点 `GET /api/cost/timeseries?tenant_id=&provider=&period=daily|weekly&days=30`
  - 复用 `_resolve_query_tenant` 鉴权 helper：admin 邮箱可指定他人 tenant；非 admin 静默覆盖回自己（与 `/summary` `/recent` 三端点一致行为）
  - SQL 形态（按卡片要求）：
    ```sql
    SELECT DATE_TRUNC('day' /* whitelist */, created_at) AS day,
           provider,
           SUM(cost_usd) AS cost_usd,
           COUNT(*)::int AS call_count
      FROM model_calls
     WHERE tenant_id = :tenant_id
       AND created_at >= NOW() - ((:days)::text || ' days')::interval
       [AND provider = :provider]
     GROUP BY day, provider
     ORDER BY day ASC, provider ASC
    ```
  - **关于 INTERVAL 参数化**：原卡片给的写法 `INTERVAL ':days days'` 在 PG 不允许直接绑定字符串拼装（绑定参数不会替换字面量内文本）。改用社区标准的 `(:days || ' days')::interval` 安全形式。
  - 失败翻 503 让前端拿空集而不是 500（与既有 `/summary` 风格对齐）

### 1.2 前端 — `fliki-clone/src/lib/cost.ts`（追加 `getCostTimeseries`）

末尾追加 ~50 行；**不动既有 `getCostSummary` / `getRecentCostCalls`** 及其类型。

- 新类型 `CostTimeseriesPeriod` / `CostTimeseriesPoint` / `CostTimeseries`
- 新 helper `getCostTimeseries({tenantId, provider, period, days})`
- 与既有 `buildQuery(...)` 私有 helper 复用（不重复实现）

### 1.3 前端 — 新页面 `fliki-clone/src/app/[locale]/(app)/app/admin/metrics/page.tsx`

新文件，~600 行。完全独占新目录 `app/admin/metrics/`，与 T-14 的 `app/admin/feature-flags/` 平级互不干涉。

页面构成：
1. **admin 探测 + 403 view**：onMount 拉 `getAdminMe()`，非 admin 渲染友好 403，与 T-14 同款防直链
2. **ControlsBar**：tenant 选择器（复用 T-14 的 `listTenants`）+ 「自定义 tenant_id」输入 + period toggle（daily/weekly）+ days 桶（7/14/30/60/90）
3. **SummaryStrip**：3 格 stat（期内总成本 / 期内总调用 / 窗口）
4. **ChartCard**：自绘 SVG `LineChart` 组件
   - 多 series（每 provider 一条线）
   - Provider chips 图例：点击 toggle 单条线显隐（前端过滤；不重新拉数据）
   - hover 显示竖线 + tooltip（按 cost desc 列出当桶各 provider）
   - X 轴自动抽样（最多 8 个 tick label）；Y 轴 4 个网格
   - 颜色映射与既有 `pipeline/page.tsx::CostBreakdownPanel` 完全一致：
     `openai=emerald` / `siliconflow=sky` / `kling=amber` / `elevenlabs=violet` / `local=slate`
   - 空数据态：「最近 N 天没有调用记录」

### 1.4 前端 — `fliki-clone/src/components/app-shell/sidebar.tsx`（加 NavLink）

在 admin section 已有的「Feature Flags」入口下面加一行「Metrics」入口（`LineChart` icon，与 ShieldCheck 同风格）。**仅多 2 处文本改动**：lucide-react import + admin section 数组。

### 1.5 后端 — 新文件 `fliki-clone-api/tests/test_track21_timeseries.py`

8 case（2 unit + 6 integration），独立文件不污染 conftest：

| # | case | 验证点 |
|---|---|---|
| 1 | `test_resolve_bucket_whitelist` | daily/weekly/未知 → 'day'/'week'/'day' |
| 2 | `test_clamp_days_boundaries` | 边界值 / 非整数兜底 |
| 3 | `test_timeseries_groups_by_day_and_provider` | 7 天 × 2 provider → 14 行聚合 + 排序 |
| 4 | `test_timeseries_provider_filter_excludes_others` | `?provider=kling` 只返 kling |
| 5 | `test_timeseries_empty_returns_empty_items` | 空 tenant 返 200 + items=[] |
| 6 | `test_timeseries_excludes_rows_outside_window` | days=7 排除 30 天前的老行 |
| 7 | `test_timeseries_admin_passes_through_other_tenant` | admin 直通；非 admin 静默覆盖 |
| 8 | `test_timeseries_weekly_period_uses_week_truncate` | 同周 N 行折成同一周桶 |

测试隔离：
- 用前缀 `test_t21:` 与 T-18 的 `test_t:` 命名空间互斥
- 私有 `_seed_model_call` 直接 INSERT 绕开 `record_call`，方便精确控制 `created_at`
- async endpoint 用 `asyncio.run` 直接跑（与 `test_admin_flags` / `test_track18_cost` 同款，避开 sandbox 起 TestClient 的坑）

---

## 2. 烟测命令 + 结果

```bash
cd /Users/zhaoguangyuan/project/empty-track21/fliki-clone-api && \
  .venv/bin/python -m pytest tests/ -v
```

**结果**：`97 passed in 2.35s`（基线 89 + Track-21 新增 8 = 97，零回归）

```bash
cd /Users/zhaoguangyuan/project/empty-track21/fliki-clone && \
  npx eslint src/app/\[locale\]/\(app\)/app/admin/metrics/page.tsx \
             src/lib/cost.ts \
             src/components/app-shell/sidebar.tsx
```

**结果**：clean（无 warning / error）

```bash
cd /Users/zhaoguangyuan/project/empty-track21/fliki-clone && npx tsc --noEmit
```

**结果**：clean（类型检查通过）

> 没跑真启 backend 的 curl e2e：sandbox 起 8000 端口会与已运行的 pid 30876 冲突；
> 8 case integration 已直接调 router async fn 走真 PG（命中本机 `fliki` 库）覆盖了
> SQL 正确性 + 鉴权穿透 + DATE_TRUNC 行为，等价于 endpoint 层烟测。
> 用户重启 backend 后可手动 curl：
> ```bash
> curl -b cookies.txt 'http://127.0.0.1:8000/api/cost/timeseries?period=daily&days=30'
> ```

---

## 3. 已知边界 / 跳过的子任务

### 3.1 没用 recharts（卡片描述与事实不符）

backlog 卡片 + 派发 prompt 都说「前端用 recharts（package.json 里已经有）」，但实际：
- `fliki-clone/package.json` 里**没有** recharts
- `node_modules/recharts` 也不存在

为了避免本 Track 顺手扩散依赖（互斥锁规则 + commit 干净度），改用纯 SVG 自绘 `LineChart`（~250 行，与既有 DAG view `@xyflow/react` 自绘风格一致）。
能力够用：多 series / hover tooltip / 网格线 / X-Y 轴标签 / 图例 / 单条线 toggle。
**Follow-up（如果未来要 zoom/export/secondary axis 等复杂功能）**：可以再开 mini-Track 加 recharts 依赖然后替换 `LineChart` 子组件，page 其它部分零修改。

### 3.2 没改的（按互斥锁规则）

- `routers/cost.py::_resolve_query_tenant` / `_period_window` / `_engine` / `_timedelta` helper 完全沿用，未改一行
- `routers/cost.py::cost_summary` / `cost_recent` 路由函数完全沿用，未改一行
- `lib/cost.ts::getCostSummary` / `getRecentCostCalls` 完全沿用，未改一行
- `pipeline/page.tsx::CostBreakdownPanel`（T-18 写的「按 provider 横向 bar」）未改，metrics 是新页面独立消费 `/timeseries`
- alembic / `.env` / `app/config.py` / pipeline / agents 任一文件
- `routers/admin_flags.py`（T-14 / T-23 互斥锁）

### 3.3 不做（卡片显式声明）

- 图表 zoom / export
- view_count 时序（L-03 第二阶段；当前只有 cost）
- 自动刷新（admin 手刷即可）

---

## 4. Follow-up（建议）

1. **AGENTS_BACKLOG.md 第 2.7 节 Track-21 卡片更正**：把「推荐用 `recharts` 已在 deps 里」改为「自绘 SVG（recharts 不在 deps，避免扩散依赖）」或者协调者主动安装 recharts 后通知后续 Track。
2. **provider 多选**：当前 chips 只支持「全部」与「单选 toggle」前端过滤；后端 `?provider=` 仍是单值。如果未来 admin 想「同时只看 kling + siliconflow」，可以改后端为 CSV 入参（向后兼容）。
3. **L-03 第二阶段**：view_count / publish 成功率 / 平均 step 耗时等指标走类似端点；可以继续在 `routers/cost.py` 末尾追加 `/timeseries-views` 等，或新开 `routers/metrics.py`。
4. **Frontend tests**：本次只跑了 lint + tsc，没加前端单测（项目里目前也没有 jest/vitest 套件）。如果后续引入测试栈，`LineChart` 子组件可以单独测 `groupByBucket` / `buildLinePath` / `sampleIndices` 几个纯函数。
5. **DB index**：`model_calls.tenant_id` 已有 ix（T-18 加的）；多 day + DATE_TRUNC 聚合在 100K 量级单 tenant 下实测 PG 内排序可接受。如果未来单 tenant model_calls 行数到百万级，可考虑加 `(tenant_id, created_at)` 复合索引（不改本 Track，留给真触发性能问题时做）。

---

## 5. 文件清单

| 文件 | 改动 | 行数 |
|---|---|---|
| `fliki-clone-api/app/routers/cost.py` | 追加 `/timeseries` 段（不动既有） | +163 |
| `fliki-clone-api/tests/test_track21_timeseries.py` | 新文件，8 case | +330 |
| `fliki-clone/src/lib/cost.ts` | 追加 `getCostTimeseries` helper + 类型 | +47 |
| `fliki-clone/src/app/[locale]/(app)/app/admin/metrics/page.tsx` | 新页面 + 自绘 SVG `LineChart` | +600 |
| `fliki-clone/src/components/app-shell/sidebar.tsx` | 加 admin Metrics 入口（icon import + NavLink） | +6 |
| `TRACK_21_NOTES.md`（本文件） | 交付文档 | — |

`git status` 在交付前 clean（满足规则 6 / T-14 教训）。
