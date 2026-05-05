/**
 * Track-18 cost API client
 * ────────────────────────
 * 后端 `routers/cost.py` 提供 2 个端点：
 *
 *   - GET /api/cost/summary?tenant_id=&period=monthly|weekly|daily
 *       本期内（默认本月）该 tenant 的总成本 + 按 provider 拆分
 *
 *   - GET /api/cost/recent?tenant_id=&limit=50
 *       该 tenant 最近 N 条 model_calls 明细
 *
 * 安全约束（与后端一致）：tenant_id 不传时后端用 resolve_tenant_id(user) 推导；
 * 传了但与 user 自己 tenant 不同 → 仅 admin 通过，否则被静默覆盖回自己的 tenant。
 */
import { api } from "@/lib/api";

export type CostPeriod = "monthly" | "weekly" | "daily";

export interface ProviderCostRow {
  provider: string;
  cost_usd: number;
  call_count: number;
  success_count: number;
  failed_count: number;
}

export interface CostSummary {
  tenant_id: string;
  period: CostPeriod;
  period_start: string;
  period_end: string;
  total_cost_usd: number;
  total_calls: number;
  by_provider: ProviderCostRow[];
}

export interface RecentCall {
  id: string;
  user_id: string | null;
  file_id: string | null;
  provider: string;
  model: string | null;
  action: string;
  cost_usd: number;
  duration_ms: number;
  status: string;
  error: string | null;
  created_at: string;
}

export interface RecentCallsOut {
  tenant_id: string;
  items: RecentCall[];
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") {
      usp.append(k, String(v));
    }
  });
  const q = usp.toString();
  return q ? `?${q}` : "";
}

export function getCostSummary(args?: { tenantId?: string; period?: CostPeriod }) {
  const qs = buildQuery({ tenant_id: args?.tenantId, period: args?.period });
  return api<CostSummary>(`/cost/summary${qs}`);
}

export function getRecentCostCalls(args?: { tenantId?: string; limit?: number }) {
  const qs = buildQuery({ tenant_id: args?.tenantId, limit: args?.limit });
  return api<RecentCallsOut>(`/cost/recent${qs}`);
}
