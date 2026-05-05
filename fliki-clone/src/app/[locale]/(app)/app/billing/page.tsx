"use client";

/**
 * /app/billing —— Track-11 真实 Stripe 订阅页面。
 *
 * 与旧 /settings/billing 区别：
 * - 调真后端 GET  /api/billing/plan       拿当前 plan + tenant 配额
 * - 调真后端 POST /api/billing/checkout-session 跳 Stripe Checkout
 * - 调真后端 POST /api/billing/portal-session   跳 Stripe Customer Portal
 *
 * tenant 视图（monthly_limit_usd / concurrent_max）来自 v2 tenant_quotas，
 * webhook 处理完会立刻 bump，所以用户支付完跳回时刷新一下就能看到新额度。
 *
 * Track-27 RBAC 写权限分级
 * ------------------------
 * 计费写端点（checkout-session / portal-session）后端已挂 ``require_role(["admin"])``：
 * 非 admin 调用会 403。前端这里同样按 ``role.isAdmin`` 灰化「Upgrade to ...」+
 * 「Manage in portal」按钮 + tooltip "需要 admin 权限"，避免普通成员误点出 403。
 * 「Refresh」按钮不 disable（GET /billing/plan 不限 admin）。
 */
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCurrentRole } from "@/hooks/use-current-role";
import { api, ApiError } from "@/lib/api";
import { canManageBilling, disabledReason } from "@/lib/role";
import { cn } from "@/lib/utils";
import { Check, ExternalLink, Loader2, RefreshCw } from "lucide-react";

interface TenantPreview {
  tenant_id: string;
  tenant_plan: string;
  monthly_limit_usd: number;
  current_period_usage_usd: number;
  concurrent_max: number;
}

interface BillingPlanV2 {
  plan: string;
  status: string;
  credits_used: number;
  credits_total: number;
  current_period_end: string | null;
  stripe_customer_id: string | null;
  tenant: TenantPreview;
}

interface CheckoutResponse {
  checkout_url: string;
}

interface PortalResponse {
  portal_url: string;
}

type PlanKey = "free" | "standard" | "premium";

const PLAN_CARDS: Array<{
  key: PlanKey;
  name: string;
  price: string;
  tagline: string;
  features: string[];
  highlight?: boolean;
}> = [
  {
    key: "free",
    name: "Free",
    price: "$0",
    tagline: "$10 / month AI quota · 2 concurrent runs",
    features: ["HD export", "Basic voices", "Watermark"],
  },
  {
    key: "standard",
    name: "Standard",
    price: "$28",
    tagline: "$100 / month AI quota · 5 concurrent runs",
    features: ["1080p export", "Premium voices", "No watermark", "Priority queue"],
    highlight: true,
  },
  {
    key: "premium",
    name: "Premium",
    price: "$88",
    tagline: "$500 / month AI quota · 10 concurrent runs",
    features: [
      "Everything in Standard",
      "Voice clone",
      "Higher provider concurrency",
      "Priority support",
    ],
  },
];

const PLAN_RANK: Record<string, number> = {
  free: 0,
  standard: 1,
  premium: 2,
  enterprise: 3,
};

function planLabel(plan: string) {
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

export default function AppBillingPage() {
  const [data, setData] = useState<BillingPlanV2 | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingPlan, setPendingPlan] = useState<PlanKey | null>(null);
  const [pendingPortal, setPendingPortal] = useState(false);
  // Track-27 · 计费写端点仅 admin（与后端 require_role(["admin"]) 对齐）
  const role = useCurrentRole();
  const adminAllowed = canManageBilling(role, role.loading);
  const adminDisabledReason = disabledReason(role, role.loading, {
    adminOnly: true,
  });

  const fetchPlan = useCallback(async () => {
    try {
      const r = await api<BillingPlanV2>("/billing/plan");
      setData(r);
      setError(null);
    } catch (e) {
      const msg = e instanceof ApiError ? `API ${e.status}` : "Failed to load billing plan";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlan();
  }, [fetchPlan]);

  // 用户从 Stripe Checkout 成功跳回时通常带 ?session_id=cs_test_*；
  // webhook 可能稍滞后，给 1.5s 再 refetch 一次让 tenant 视图刷出来。
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    if (sp.get("session_id")) {
      const t = setTimeout(() => fetchPlan(), 1500);
      return () => clearTimeout(t);
    }
  }, [fetchPlan]);

  const onSelect = useCallback(
    async (planKey: PlanKey) => {
      if (planKey === "free") return;
      if (!data) return;
      setPendingPlan(planKey);
      try {
        const r = await api<CheckoutResponse>("/billing/checkout-session", {
          method: "POST",
          body: JSON.stringify({
            plan: planKey,
            success_url:
              typeof window !== "undefined"
                ? `${window.location.origin}/app/billing`
                : undefined,
            cancel_url:
              typeof window !== "undefined"
                ? `${window.location.origin}/app/billing`
                : undefined,
          }),
        });
        window.location.href = r.checkout_url;
      } catch (e) {
        const detail =
          e instanceof ApiError && typeof e.body === "object" && e.body
            ? ((e.body as { detail?: string }).detail ?? `API ${e.status}`)
            : "Checkout session failed";
        setError(detail);
        setPendingPlan(null);
      }
    },
    [data]
  );

  const onManagePortal = useCallback(async () => {
    setPendingPortal(true);
    try {
      const r = await api<PortalResponse>("/billing/portal-session", {
        method: "POST",
      });
      window.location.href = r.portal_url;
    } catch (e) {
      const detail =
        e instanceof ApiError && typeof e.body === "object" && e.body
          ? ((e.body as { detail?: string }).detail ?? `API ${e.status}`)
          : "Portal session failed";
      setError(detail);
      setPendingPortal(false);
    }
  }, []);

  const currentPlan = data?.plan ?? "free";
  const currentRank = PLAN_RANK[currentPlan] ?? 0;
  const tenant = data?.tenant;
  const usagePct = tenant && tenant.monthly_limit_usd > 0
    ? Math.min(100, (tenant.current_period_usage_usd / tenant.monthly_limit_usd) * 100)
    : 0;

  return (
    <div className="p-7 space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text)]">Billing</h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            Manage your subscription and AI quota.{" "}
            <span className="text-[var(--text-muted)]">
              Powered by Stripe · v2 tenant_quotas synced via webhook.
            </span>
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={fetchPlan}
          disabled={loading}
          className="gap-1.5"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {error && (
        <div className="rounded-[var(--radius-lg)] border border-rose-300 bg-rose-50 px-4 py-2.5 text-xs text-rose-800">
          {error}
        </div>
      )}

      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-[var(--text)]">Current plan</h2>
              <Badge variant={currentPlan === "free" ? "default" : "primary"}>
                {planLabel(currentPlan)}
              </Badge>
              {data?.status && data.status !== "free" && (
                <span
                  className={cn(
                    "text-[10px] px-1.5 py-0.5 rounded font-medium uppercase",
                    data.status === "active"
                      ? "bg-emerald-100 text-emerald-700"
                      : data.status === "past_due"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-zinc-100 text-zinc-600"
                  )}
                >
                  {data.status}
                </span>
              )}
            </div>
            {tenant && (
              <p className="text-xs text-[var(--text-secondary)] mt-1.5">
                tenant <code className="text-[10px]">{tenant.tenant_id}</code> ·
                <span className="mx-1.5">monthly limit</span>
                <strong>${tenant.monthly_limit_usd.toFixed(2)}</strong>
                <span className="mx-1.5">·</span>
                <span>concurrent</span>
                <strong className="ml-1">{tenant.concurrent_max}</strong>
              </p>
            )}
            {data?.current_period_end && (
              <p className="text-[11px] text-[var(--text-muted)] mt-1">
                Current period ends {new Date(data.current_period_end).toLocaleDateString()}
              </p>
            )}
          </div>
          {data?.stripe_customer_id && (
            <Button
              variant="outline"
              size="sm"
              onClick={onManagePortal}
              disabled={pendingPortal || !adminAllowed}
              title={adminDisabledReason ?? undefined}
              className="gap-1.5"
            >
              {pendingPortal ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ExternalLink className="h-3.5 w-3.5" />
              )}
              Manage subscription
            </Button>
          )}
        </div>

        {tenant && (
          <div className="mt-5">
            <div className="h-2 rounded-full bg-[var(--bg-muted)] overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  usagePct >= 95
                    ? "bg-rose-500"
                    : usagePct >= 70
                      ? "bg-amber-500"
                      : "bg-[var(--brand-600)]"
                )}
                style={{ width: `${usagePct}%` }}
              />
            </div>
            <p className="text-[11px] text-[var(--text-muted)] mt-1.5">
              ${tenant.current_period_usage_usd.toFixed(4)} of ${tenant.monthly_limit_usd.toFixed(2)} used this period
              · {usagePct.toFixed(1)}%
            </p>
          </div>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold text-[var(--text)] mb-3">Choose a plan</h3>
        <div className="grid sm:grid-cols-3 gap-3">
          {PLAN_CARDS.map((p) => {
            const rank = PLAN_RANK[p.key];
            const isCurrent = currentPlan === p.key;
            const isUpgrade = rank > currentRank;
            const isDowngrade = rank < currentRank;
            const buttonLabel = isCurrent
              ? "Current plan"
              : isUpgrade
                ? p.key === "free"
                  ? "Downgrade via portal"
                  : `Upgrade to ${p.name}`
                : isDowngrade
                  ? "Manage in portal"
                  : `Switch to ${p.name}`;
            const onClick = () => {
              if (isCurrent) return;
              if (p.key === "free" || isDowngrade) {
                if (data?.stripe_customer_id) onManagePortal();
                return;
              }
              onSelect(p.key);
            };
            const disabled =
              isCurrent ||
              pendingPlan === p.key ||
              (p.key === "free" && !data?.stripe_customer_id) ||
              !adminAllowed;
            const titleText = !adminAllowed ? adminDisabledReason : undefined;

            return (
              <div
                key={p.key}
                className={cn(
                  "rounded-[var(--radius-xl)] border p-5 flex flex-col bg-[var(--surface)]",
                  p.highlight ? "border-[var(--brand-600)] shadow-md" : "border-[var(--border)]",
                  isCurrent && "ring-2 ring-emerald-400/60"
                )}
              >
                <div className="flex items-start justify-between">
                  <p className="font-semibold text-[var(--text)]">{p.name}</p>
                  {isCurrent && (
                    <Badge variant="primary" className="text-[10px]">
                      Active
                    </Badge>
                  )}
                </div>
                <p className="text-2xl font-bold text-[var(--text)] mt-2">
                  {p.price}
                  <span className="text-sm font-normal text-[var(--text-muted)]">/mo</span>
                </p>
                <p className="text-[11px] text-[var(--text-secondary)] mt-1">{p.tagline}</p>
                <ul className="mt-4 space-y-1.5 flex-1">
                  {p.features.map((f) => (
                    <li
                      key={f}
                      className="flex gap-2 text-xs text-[var(--text-secondary)]"
                    >
                      <Check className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                      {f}
                    </li>
                  ))}
                </ul>
                <Button
                  size="sm"
                  className="mt-4 w-full gap-1.5"
                  variant={p.highlight && isUpgrade ? "primary" : "outline"}
                  onClick={onClick}
                  disabled={disabled}
                >
                  {pendingPlan === p.key ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : null}
                  {buttonLabel}
                </Button>
              </div>
            );
          })}
        </div>
      </section>

      <p className="text-xs text-[var(--text-muted)]">
        After payment, Stripe webhook will sync your plan to{" "}
        <code>tenant_quotas</code> and bump <code>monthly_limit_usd</code> /{" "}
        <code>concurrent_max</code> / per-provider concurrency buckets automatically.
      </p>
    </div>
  );
}
