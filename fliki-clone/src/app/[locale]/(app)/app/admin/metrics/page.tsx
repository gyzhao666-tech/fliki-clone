"use client";

/**
 * Admin · Metrics 页（Track-21 / L-03 metric dashboard）。
 *
 * 范围
 * ----
 * - 顶部 stat：总成本 + 总调用次数（period 内）
 * - tenant 选择器（复用 T-14 的 `listTenants`）
 * - provider 多选 chips：前端做「显示哪些 series」过滤；服务端 `?provider=` 仅
 *   单值过滤，所以「全部 provider」拉一次（多 series），「单选」拉单 provider。
 * - period toggle：daily / weekly
 * - days 桶：7 / 14 / 30 / 60 / 90
 * - 折线图：自绘 SVG（每 provider 一条线 + 颜色标签 + hover 节点）
 *
 * 显式不做（与 backlog 卡片一致）
 * --------------------------------
 * - 图表 zoom / export（v1 静态图够用）
 * - view_count 时序（L-03 第二阶段；当前只有 cost）
 * - 不动既有 /summary /recent 端点 + 不动 page.tsx::CostBreakdownPanel
 *
 * 鉴权两层兜底
 * ------------
 * 1. `Sidebar` 已经按 `getAdminMe()` 隐藏入口
 * 2. 本页 onMount 也调一次 `getAdminMe()`，非 admin 直接渲 403 view（防直链）
 *
 * 没用 recharts 的原因
 * --------------------
 * Backlog 卡片 / 派发 prompt 都说 "recharts 已在 deps 里"，但实际没在
 * `package.json` 里也没装。为了避免本 Track 顺手扩散依赖（互斥锁规则），
 * 这里用纯 SVG 自绘多 series LineChart（~250 行，跟既有 DAG view 自绘风格一致）。
 * 图表能力够用：多 series / hover tooltip / 网格线 / X-Y 标签 / 图例。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Loader2,
  RefreshCw,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type AdminMeOut,
  type TenantSummary,
  getAdminMe,
  listTenants,
} from "@/lib/admin-flags";
import {
  type CostTimeseries,
  type CostTimeseriesPeriod,
  type CostTimeseriesPoint,
  getCostTimeseries,
} from "@/lib/cost";
import { cn } from "@/lib/utils";

// 与 page.tsx::CostBreakdownPanel 同款颜色（保持视觉一致）
const PROVIDER_COLORS: Record<string, string> = {
  openai: "#10b981", // emerald
  siliconflow: "#0284c7", // sky
  kling: "#f59e0b", // amber
  elevenlabs: "#8b5cf6", // violet
  local: "#64748b", // slate
};
const FALLBACK_COLORS = [
  "#0284c7",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#64748b",
  "#0ea5e9",
];

const DAYS_OPTIONS = [7, 14, 30, 60, 90] as const;
type DaysOption = (typeof DAYS_OPTIONS)[number];

interface PageState {
  me: AdminMeOut | null;
  tenants: TenantSummary[];
  selectedTenant: string;
  customTenantInput: string;
  period: CostTimeseriesPeriod;
  days: DaysOption;
  /** 「全部」时为空数组；前端过滤展示哪些 series。后端永远拉全部数据。 */
  providerFilter: string[];
  data: CostTimeseries | null;
  loadingTenants: boolean;
  loadingData: boolean;
  pageError: string | null;
}

const initialState: PageState = {
  me: null,
  tenants: [],
  selectedTenant: "",
  customTenantInput: "",
  period: "daily",
  days: 30,
  providerFilter: [],
  data: null,
  loadingTenants: true,
  loadingData: false,
  pageError: null,
};

export default function AdminMetricsPage() {
  const [state, setState] = useState<PageState>(initialState);

  // ── me 探测 + tenant 列表 ────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await getAdminMe();
        if (cancelled) return;
        if (!me.is_admin) {
          setState((s) => ({
            ...s,
            me,
            loadingTenants: false,
            pageError:
              "Forbidden: 当前账户邮箱不在 ADMIN_EMAILS 白名单。请联系协调者添加。",
          }));
          return;
        }
        const list = await listTenants();
        if (cancelled) return;
        setState((s) => ({
          ...s,
          me,
          tenants: list.tenants,
          loadingTenants: false,
          selectedTenant: list.tenants[0]?.tenant_id ?? "",
        }));
      } catch (err) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          loadingTenants: false,
          pageError:
            err instanceof ApiError
              ? `加载 admin 信息失败 (${err.status})`
              : "加载 admin 信息失败",
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // ── tenant / period / days 变化 → 重新拉时序 ────────────────────────────
  useEffect(() => {
    const tid = state.selectedTenant;
    if (!tid || !state.me?.is_admin) return;
    let cancelled = false;
    setState((s) => ({ ...s, loadingData: true, pageError: null }));
    (async () => {
      try {
        const data = await getCostTimeseries({
          tenantId: tid,
          period: state.period,
          days: state.days,
        });
        if (cancelled) return;
        setState((s) => ({ ...s, data, loadingData: false }));
      } catch (err) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          loadingData: false,
          pageError:
            err instanceof ApiError
              ? `成本时序拉取失败 (${err.status})`
              : "成本时序拉取失败",
          data: null,
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state.selectedTenant, state.period, state.days, state.me?.is_admin]);

  const refetchTenants = useCallback(async () => {
    setState((s) => ({ ...s, loadingTenants: true }));
    try {
      const list = await listTenants();
      setState((s) => ({
        ...s,
        tenants: list.tenants,
        loadingTenants: false,
      }));
    } catch (err) {
      setState((s) => ({
        ...s,
        loadingTenants: false,
        pageError:
          err instanceof ApiError
            ? `tenant 列表刷新失败 (${err.status})`
            : "tenant 列表刷新失败",
      }));
    }
  }, []);

  const handleSwitchToCustom = useCallback(() => {
    const v = state.customTenantInput.trim();
    if (!v) return;
    setState((s) => ({
      ...s,
      selectedTenant: v,
      customTenantInput: "",
    }));
  }, [state.customTenantInput]);

  // ── render branches ──────────────────────────────────────────────────────

  if (!state.me) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--text-muted)]">
        <Loader2 className="h-5 w-5 animate-spin mr-2" /> 检查 admin 权限…
      </div>
    );
  }

  if (!state.me.is_admin) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-12">
        <div className="flex items-start gap-3 rounded-[var(--radius-xl)] border border-amber-300 bg-amber-50 p-5">
          <ShieldAlert className="h-5 w-5 text-amber-600 mt-0.5" />
          <div>
            <h2 className="text-base font-semibold text-amber-900">
              你不是 admin
            </h2>
            <p className="mt-1 text-sm text-amber-800">
              当前账户邮箱{" "}
              <code className="rounded bg-amber-100 px-1.5 py-0.5 text-xs">
                {state.me.email ?? "(unknown)"}
              </code>{" "}
              不在 <code>ADMIN_EMAILS</code> 白名单。请联系协调者把邮箱加进
              backend env 后刷新。
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">
            Admin · Metrics
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            按 tenant × provider 的成本时序 · admin{" "}
            <Badge variant="primary">{state.me.email}</Badge>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={refetchTenants}
            loading={state.loadingTenants}
          >
            <RefreshCw className="h-4 w-4" /> 刷新 tenants
          </Button>
        </div>
      </header>

      {state.pageError && (
        <div className="flex items-start gap-2 rounded-[var(--radius-lg)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" /> {state.pageError}
        </div>
      )}

      <ControlsBar
        tenants={state.tenants}
        selectedTenant={state.selectedTenant}
        customTenantInput={state.customTenantInput}
        period={state.period}
        days={state.days}
        onSelectTenant={(tid) =>
          setState((s) => ({
            ...s,
            selectedTenant: tid,
            providerFilter: [],
            customTenantInput: "",
          }))
        }
        onCustomChange={(v) =>
          setState((s) => ({ ...s, customTenantInput: v }))
        }
        onSwitchToCustom={handleSwitchToCustom}
        onPeriodChange={(p) => setState((s) => ({ ...s, period: p }))}
        onDaysChange={(d) => setState((s) => ({ ...s, days: d }))}
      />

      <SummaryStrip data={state.data} loading={state.loadingData} />

      <ChartCard
        data={state.data}
        loading={state.loadingData}
        period={state.period}
        days={state.days}
        providerFilter={state.providerFilter}
        onToggleProvider={(p) =>
          setState((s) => ({
            ...s,
            providerFilter: s.providerFilter.includes(p)
              ? s.providerFilter.filter((x) => x !== p)
              : [...s.providerFilter, p],
          }))
        }
        onClearFilter={() =>
          setState((s) => ({ ...s, providerFilter: [] }))
        }
      />
    </div>
  );
}

// ── 控件条 ─────────────────────────────────────────────────────────────────

function ControlsBar({
  tenants,
  selectedTenant,
  customTenantInput,
  period,
  days,
  onSelectTenant,
  onCustomChange,
  onSwitchToCustom,
  onPeriodChange,
  onDaysChange,
}: {
  tenants: TenantSummary[];
  selectedTenant: string;
  customTenantInput: string;
  period: CostTimeseriesPeriod;
  days: DaysOption;
  onSelectTenant: (tid: string) => void;
  onCustomChange: (v: string) => void;
  onSwitchToCustom: () => void;
  onPeriodChange: (p: CostTimeseriesPeriod) => void;
  onDaysChange: (d: DaysOption) => void;
}) {
  return (
    <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5 min-w-[260px]">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            Tenant
          </label>
          <select
            value={selectedTenant}
            onChange={(e) => onSelectTenant(e.target.value)}
            className="h-10 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
          >
            <option value="">{tenants.length === 0 ? "（暂无 tenant）" : "选择 tenant"}</option>
            {tenants.map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.tenant_id} · {t.flag_count} flag
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            或自定义 tenant_id
          </label>
          <div className="flex gap-2">
            <input
              value={customTenantInput}
              onChange={(e) => onCustomChange(e.target.value)}
              placeholder="ws:... / u:..."
              className="h-10 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm w-[200px]"
            />
            <Button size="sm" variant="secondary" onClick={onSwitchToCustom}>
              查看
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            桶
          </label>
          <div className="flex rounded-[var(--radius-md)] border border-[var(--border)] overflow-hidden">
            {(["daily", "weekly"] as const).map((p) => (
              <button
                key={p}
                onClick={() => onPeriodChange(p)}
                className={cn(
                  "px-3 py-2 text-sm font-medium transition-colors",
                  period === p
                    ? "bg-[var(--brand-600)] text-white"
                    : "bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
                )}
              >
                {p === "daily" ? "按天" : "按周"}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            回看天数
          </label>
          <div className="flex rounded-[var(--radius-md)] border border-[var(--border)] overflow-hidden">
            {DAYS_OPTIONS.map((d) => (
              <button
                key={d}
                onClick={() => onDaysChange(d)}
                className={cn(
                  "px-3 py-2 text-sm font-medium transition-colors",
                  days === d
                    ? "bg-[var(--brand-600)] text-white"
                    : "bg-[var(--surface)] text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
                )}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 顶部数字带 ─────────────────────────────────────────────────────────────

function SummaryStrip({
  data,
  loading,
}: {
  data: CostTimeseries | null;
  loading: boolean;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Stat
        title="期内总成本"
        value={
          data ? `$${data.total_cost_usd.toFixed(4)}` : loading ? "…" : "—"
        }
        icon={<TrendingUp className="h-4 w-4 text-[var(--brand-600)]" />}
      />
      <Stat
        title="期内总调用"
        value={data ? data.total_calls.toLocaleString() : loading ? "…" : "—"}
      />
      <Stat
        title="窗口"
        value={
          data
            ? `${formatDate(data.period_start)} → ${formatDate(data.period_end)}`
            : "—"
        }
        small
      />
    </div>
  );
}

function Stat({
  title,
  value,
  icon,
  small,
}: {
  title: string;
  value: string;
  icon?: React.ReactNode;
  small?: boolean;
}) {
  return (
    <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-[var(--text-secondary)]">
        {icon} {title}
      </div>
      <div
        className={cn(
          "mt-2 font-bold text-[var(--text)]",
          small ? "text-sm" : "text-2xl"
        )}
      >
        {value}
      </div>
    </div>
  );
}

// ── 折线图卡片 ─────────────────────────────────────────────────────────────

function ChartCard({
  data,
  loading,
  period,
  days,
  providerFilter,
  onToggleProvider,
  onClearFilter,
}: {
  data: CostTimeseries | null;
  loading: boolean;
  period: CostTimeseriesPeriod;
  days: number;
  providerFilter: string[];
  onToggleProvider: (provider: string) => void;
  onClearFilter: () => void;
}) {
  const allProviders = useMemo(() => {
    if (!data) return [] as string[];
    const set = new Set(data.items.map((p) => p.provider));
    return Array.from(set).sort();
  }, [data]);

  const visibleProviders = useMemo(() => {
    if (providerFilter.length === 0) return allProviders;
    return allProviders.filter((p) => providerFilter.includes(p));
  }, [allProviders, providerFilter]);

  return (
    <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text)]">
            按 provider 成本时序
          </h2>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            {period === "daily" ? "按天聚合" : "按周聚合"} · 最近 {days} 天
            {data && data.items.length > 0
              ? ` · ${allProviders.length} provider`
              : ""}
          </p>
        </div>
        {providerFilter.length > 0 && (
          <Button size="sm" variant="ghost" onClick={onClearFilter}>
            清除过滤
          </Button>
        )}
      </div>

      {/* legend / chip 过滤器 */}
      {allProviders.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-3">
          {allProviders.map((p, i) => {
            const active =
              providerFilter.length === 0 || providerFilter.includes(p);
            return (
              <button
                key={p}
                onClick={() => onToggleProvider(p)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-[var(--radius-full)] border px-2.5 py-0.5 text-xs font-medium transition-colors",
                  active
                    ? "border-[var(--border-strong)] bg-[var(--surface)] text-[var(--text)]"
                    : "border-[var(--border)] bg-[var(--bg-muted)] text-[var(--text-muted)] line-through"
                )}
              >
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: providerColor(p, i) }}
                />
                {p}
              </button>
            );
          })}
        </div>
      )}

      <div className="relative min-h-[320px]">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--surface)]/70">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--brand-600)]" />
          </div>
        )}
        {!loading && (!data || data.items.length === 0) && (
          <div className="flex h-[320px] items-center justify-center text-sm text-[var(--text-muted)]">
            最近 {days} 天没有调用记录
          </div>
        )}
        {data && data.items.length > 0 && (
          <LineChart
            items={data.items}
            providers={visibleProviders}
            allProviders={allProviders}
            period={period}
          />
        )}
      </div>
    </div>
  );
}

// ── 自绘 SVG LineChart ─────────────────────────────────────────────────────

interface ChartGroup {
  date: string;
  bucketLabel: string;
  perProvider: Map<string, number>;
}

const CHART_W = 880;
const CHART_H = 320;
const PAD_T = 16;
const PAD_R = 24;
const PAD_B = 40;
const PAD_L = 60;

function LineChart({
  items,
  providers,
  allProviders,
  period,
}: {
  items: CostTimeseriesPoint[];
  providers: string[];
  allProviders: string[];
  period: CostTimeseriesPeriod;
}) {
  const [hover, setHover] = useState<{ x: number; idx: number } | null>(null);

  const groups = useMemo(() => groupByBucket(items, period), [items, period]);
  const maxY = useMemo(() => {
    let m = 0;
    for (const g of groups) {
      for (const p of providers) {
        const v = g.perProvider.get(p) ?? 0;
        if (v > m) m = v;
      }
    }
    return m;
  }, [groups, providers]);

  if (groups.length === 0) return null;

  const innerW = CHART_W - PAD_L - PAD_R;
  const innerH = CHART_H - PAD_T - PAD_B;
  // 单点时给左右各一点 padding；多点时按 (i / (n-1)) 等距
  const xOf = (idx: number) =>
    PAD_L + (groups.length === 1 ? innerW / 2 : (innerW * idx) / (groups.length - 1));
  const yOf = (v: number) =>
    PAD_T + innerH * (1 - (maxY > 0 ? v / maxY : 0));

  const yTicks = makeYTicks(maxY, 4);
  // X 轴 tick 抽样：最多 8 个
  const xTickIndices = sampleIndices(groups.length, 8);

  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`}
      className="w-full"
      role="img"
      aria-label="按 provider 成本时序折线图"
      onMouseLeave={() => setHover(null)}
      onMouseMove={(e) => {
        const rect = (e.target as SVGElement).ownerSVGElement!.getBoundingClientRect();
        const ratio = CHART_W / rect.width;
        const px = (e.clientX - rect.left) * ratio;
        if (px < PAD_L || px > CHART_W - PAD_R) {
          setHover(null);
          return;
        }
        const localX = px - PAD_L;
        const idx =
          groups.length === 1
            ? 0
            : Math.round((localX / innerW) * (groups.length - 1));
        const clamped = Math.max(0, Math.min(groups.length - 1, idx));
        setHover({ x: xOf(clamped), idx: clamped });
      }}
    >
      {/* Y 网格 */}
      {yTicks.map((t, i) => {
        const y = yOf(t);
        return (
          <g key={`yg-${i}`}>
            <line
              x1={PAD_L}
              x2={CHART_W - PAD_R}
              y1={y}
              y2={y}
              stroke="var(--border)"
              strokeDasharray="2 3"
            />
            <text
              x={PAD_L - 8}
              y={y + 3}
              fontSize={10}
              textAnchor="end"
              fill="var(--text-muted)"
            >
              ${t.toFixed(t < 0.01 ? 4 : t < 1 ? 3 : 2)}
            </text>
          </g>
        );
      })}

      {/* X tick label */}
      {xTickIndices.map((i) => {
        const g = groups[i];
        return (
          <text
            key={`xt-${i}`}
            x={xOf(i)}
            y={CHART_H - PAD_B + 16}
            fontSize={10}
            textAnchor="middle"
            fill="var(--text-muted)"
          >
            {g.bucketLabel}
          </text>
        );
      })}

      {/* 折线 */}
      {providers.map((p, pi) => {
        const color = providerColor(
          p,
          allProviders.indexOf(p) >= 0 ? allProviders.indexOf(p) : pi
        );
        const path = buildLinePath(groups, p, xOf, yOf);
        return (
          <g key={p}>
            <path
              d={path}
              fill="none"
              stroke={color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {groups.map((g, i) => {
              const v = g.perProvider.get(p) ?? 0;
              if (v === 0) return null;
              return (
                <circle
                  key={`${p}-${i}`}
                  cx={xOf(i)}
                  cy={yOf(v)}
                  r={hover?.idx === i ? 4 : 2.5}
                  fill={color}
                  stroke="white"
                  strokeWidth={1}
                />
              );
            })}
          </g>
        );
      })}

      {/* hover 竖线 + tooltip */}
      {hover && (
        <g>
          <line
            x1={hover.x}
            x2={hover.x}
            y1={PAD_T}
            y2={CHART_H - PAD_B}
            stroke="var(--border-strong)"
            strokeDasharray="3 3"
          />
          <HoverTooltip
            group={groups[hover.idx]}
            providers={providers}
            allProviders={allProviders}
            anchorX={hover.x}
            chartW={CHART_W}
          />
        </g>
      )}
    </svg>
  );
}

function HoverTooltip({
  group,
  providers,
  allProviders,
  anchorX,
  chartW,
}: {
  group: ChartGroup;
  providers: string[];
  allProviders: string[];
  anchorX: number;
  chartW: number;
}) {
  const rows = providers
    .map((p, i) => ({
      p,
      v: group.perProvider.get(p) ?? 0,
      color: providerColor(
        p,
        allProviders.indexOf(p) >= 0 ? allProviders.indexOf(p) : i
      ),
    }))
    .filter((r) => r.v > 0)
    .sort((a, b) => b.v - a.v);
  if (rows.length === 0) return null;

  const w = 180;
  const h = 22 + rows.length * 14;
  const tx = Math.min(chartW - PAD_R - w, Math.max(PAD_L, anchorX + 8));
  const ty = PAD_T;

  return (
    <g transform={`translate(${tx}, ${ty})`}>
      <rect
        width={w}
        height={h}
        rx={6}
        ry={6}
        fill="var(--surface)"
        stroke="var(--border-strong)"
      />
      <text x={8} y={14} fontSize={11} fontWeight={600} fill="var(--text)">
        {group.bucketLabel}
      </text>
      {rows.map((r, i) => (
        <g key={r.p} transform={`translate(8, ${22 + i * 14})`}>
          <rect width={8} height={8} y={2} rx={2} fill={r.color} />
          <text x={14} y={10} fontSize={11} fill="var(--text-secondary)">
            {r.p}
          </text>
          <text
            x={w - 16}
            y={10}
            fontSize={11}
            textAnchor="end"
            fill="var(--text)"
          >
            ${r.v.toFixed(r.v < 0.01 ? 5 : r.v < 1 ? 4 : 3)}
          </text>
        </g>
      ))}
    </g>
  );
}

// ── 数据/几何 helpers ──────────────────────────────────────────────────────

function groupByBucket(
  items: CostTimeseriesPoint[],
  period: CostTimeseriesPeriod
): ChartGroup[] {
  const byKey = new Map<string, ChartGroup>();
  for (const it of items) {
    const key = it.date;
    let g = byKey.get(key);
    if (!g) {
      g = {
        date: key,
        bucketLabel: formatBucket(key, period),
        perProvider: new Map(),
      };
      byKey.set(key, g);
    }
    g.perProvider.set(
      it.provider,
      (g.perProvider.get(it.provider) ?? 0) + it.cost_usd
    );
  }
  return Array.from(byKey.values()).sort((a, b) =>
    a.date < b.date ? -1 : a.date > b.date ? 1 : 0
  );
}

function buildLinePath(
  groups: ChartGroup[],
  provider: string,
  xOf: (i: number) => number,
  yOf: (v: number) => number
): string {
  const parts: string[] = [];
  for (let i = 0; i < groups.length; i++) {
    const v = groups[i].perProvider.get(provider) ?? 0;
    parts.push(`${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`);
  }
  return parts.join(" ");
}

function makeYTicks(max: number, count: number): number[] {
  if (max <= 0) return [0];
  const out: number[] = [];
  for (let i = 0; i <= count; i++) {
    out.push((max * i) / count);
  }
  return out;
}

function sampleIndices(n: number, max: number): number[] {
  if (n <= max) return Array.from({ length: n }, (_, i) => i);
  const out: number[] = [];
  for (let i = 0; i < max; i++) {
    out.push(Math.round((i * (n - 1)) / (max - 1)));
  }
  return out;
}

function providerColor(p: string, fallbackIdx: number): string {
  return (
    PROVIDER_COLORS[p.toLowerCase()] ??
    FALLBACK_COLORS[fallbackIdx % FALLBACK_COLORS.length]
  );
}

function formatDate(s: string): string {
  try {
    return new Date(s).toISOString().slice(0, 10);
  } catch {
    return s;
  }
}

function formatBucket(s: string, period: CostTimeseriesPeriod): string {
  try {
    const d = new Date(s);
    const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(d.getUTCDate()).padStart(2, "0");
    if (period === "weekly") {
      return `Wk ${mm}-${dd}`;
    }
    return `${mm}-${dd}`;
  } catch {
    return s.slice(5, 10);
  }
}
