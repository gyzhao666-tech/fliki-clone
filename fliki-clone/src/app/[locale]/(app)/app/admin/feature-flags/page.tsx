"use client";

/**
 * Admin · Feature Flags 管理面板（Track-14 / 灰度发布可视化）。
 *
 * 范围
 * ----
 * - 把 Track-10 的 `/api/admin/feature-flags` HTTP API 包成可用 UI
 * - 顶部 tenant 选择器（拉 `/tenants` 列表 + 「自定义 tenant_id」便于对从未设过
 *   flag 的 tenant 第一次写）
 * - 表格：flag_name / value 编辑器（按 `pct` / `enabled` / `variant` / raw 形态
 *   分支渲染）/ updated 时间隐式（admin 关心的是「现在生效什么」）/ Apply / Delete
 * - 「新增 flag」dialog：known_flags 下拉 hint + 自定义名 + 形态选择器
 *
 * 显式不做（与 backlog 卡片一致）
 * --------------------------------
 * - 完整 RBAC（L-05 长尾）
 * - 后端 audit log（前端可在 follow-up 加表头展示「最近 N 次变更」）
 *
 * 鉴权两层兜底
 * ------------
 * 1. `Sidebar` 已经按 `getAdminMe()` 隐藏入口
 * 2. 本页 onMount 也调一次 `getAdminMe()`，非 admin 直接渲染 403 view（防直链）
 *    后端每条端点也是 `_require_admin` 兜底，前端只是降噪
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  ShieldAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import {
  type AdminFlagOut,
  type AdminMeOut,
  type FlagListOut,
  type FlagShape,
  type FlagValue,
  type TenantSummary,
  detectFlagShape,
  deleteTenantFlag,
  getAdminMe,
  listTenantFlags,
  listTenants,
  setTenantFlag,
} from "@/lib/admin-flags";
import { cn } from "@/lib/utils";

interface PageState {
  me: AdminMeOut | null;
  tenants: TenantSummary[];
  knownFlags: Record<string, string>;
  flags: FlagListOut | null;
  selectedTenant: string;
  customTenantInput: string;
  loadingTenants: boolean;
  loadingFlags: boolean;
  pageError: string | null;
  banner: string | null;
}

const initialState: PageState = {
  me: null,
  tenants: [],
  knownFlags: {},
  flags: null,
  selectedTenant: "",
  customTenantInput: "",
  loadingTenants: true,
  loadingFlags: false,
  pageError: null,
  banner: null,
};

export default function AdminFeatureFlagsPage() {
  const [state, setState] = useState<PageState>(initialState);
  const [showCreate, setShowCreate] = useState(false);
  const [pendingFlag, setPendingFlag] = useState<string | null>(null);

  const setBanner = useCallback((banner: string | null) => {
    setState((s) => ({ ...s, banner }));
    if (banner) {
      setTimeout(() => {
        setState((s) => (s.banner === banner ? { ...s, banner: null } : s));
      }, 2500);
    }
  }, []);

  // ── 初次加载：me 探测 + tenant 列表 ────────────────────────────────────────
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
          knownFlags: list.known_flags,
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

  // ── 选定 tenant 后拉 flag 列表 ────────────────────────────────────────────
  useEffect(() => {
    const tid = state.selectedTenant;
    if (!tid || !state.me?.is_admin) return;
    let cancelled = false;
    setState((s) => ({ ...s, loadingFlags: true, pageError: null }));
    (async () => {
      try {
        const flags = await listTenantFlags(tid);
        if (cancelled) return;
        setState((s) => ({
          ...s,
          flags,
          loadingFlags: false,
          knownFlags: { ...s.knownFlags, ...flags.known_flags },
        }));
      } catch (err) {
        if (cancelled) return;
        setState((s) => ({
          ...s,
          loadingFlags: false,
          pageError:
            err instanceof ApiError
              ? `tenant=${tid} 拉取失败 (${err.status})`
              : `tenant=${tid} 拉取失败`,
          flags: { tenant_id: tid, flags: {}, known_flags: s.knownFlags },
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [state.selectedTenant, state.me?.is_admin]);

  const refetchTenants = useCallback(async () => {
    setState((s) => ({ ...s, loadingTenants: true }));
    try {
      const list = await listTenants();
      setState((s) => ({
        ...s,
        tenants: list.tenants,
        knownFlags: { ...s.knownFlags, ...list.known_flags },
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

  const handleApply = useCallback(
    async (flagName: string, value: FlagValue) => {
      const tid = state.selectedTenant;
      if (!tid) return;
      setPendingFlag(flagName);
      try {
        const written = await setTenantFlag(tid, flagName, value);
        setState((s) => ({
          ...s,
          flags: s.flags
            ? {
                ...s.flags,
                flags: { ...s.flags.flags, [flagName]: written.value_json },
              }
            : s.flags,
        }));
        setBanner(`已写入 ${tid} · ${flagName}`);
      } catch (err) {
        setState((s) => ({
          ...s,
          pageError:
            err instanceof ApiError
              ? `写入失败 (${err.status})${
                  typeof err.body === "object" && err.body && "detail" in err.body
                    ? ": " + String((err.body as { detail: unknown }).detail)
                    : ""
                }`
              : "写入失败",
        }));
      } finally {
        setPendingFlag(null);
      }
    },
    [state.selectedTenant, setBanner]
  );

  const handleDelete = useCallback(
    async (flagName: string) => {
      const tid = state.selectedTenant;
      if (!tid) return;
      if (!window.confirm(`确认删除 ${tid} 的 flag「${flagName}」？`)) return;
      setPendingFlag(flagName);
      try {
        const out = await deleteTenantFlag(tid, flagName);
        setState((s) => ({
          ...s,
          flags: s.flags
            ? (() => {
                const next = { ...s.flags.flags };
                delete next[flagName];
                return { ...s.flags, flags: next };
              })()
            : s.flags,
        }));
        setBanner(out.deleted ? `已删除 ${flagName}` : `${flagName} 原本不存在`);
      } catch (err) {
        setState((s) => ({
          ...s,
          pageError:
            err instanceof ApiError ? `删除失败 (${err.status})` : "删除失败",
        }));
      } finally {
        setPendingFlag(null);
      }
    },
    [state.selectedTenant, setBanner]
  );

  const handleCreate = useCallback(
    async (flagName: string, value: FlagValue) => {
      const tid = state.selectedTenant || state.customTenantInput.trim();
      if (!tid) {
        setState((s) => ({
          ...s,
          pageError: "请先选择或输入一个 tenant_id",
        }));
        return;
      }
      setPendingFlag(flagName);
      try {
        await setTenantFlag(tid, flagName, value);
        setShowCreate(false);
        setBanner(`已写入 ${tid} · ${flagName}`);
        await refetchTenants();
        setState((s) => ({
          ...s,
          selectedTenant: tid,
          customTenantInput: "",
        }));
      } catch (err) {
        setState((s) => ({
          ...s,
          pageError:
            err instanceof ApiError
              ? `写入失败 (${err.status})`
              : "写入失败",
        }));
      } finally {
        setPendingFlag(null);
      }
    },
    [state.selectedTenant, state.customTenantInput, refetchTenants, setBanner]
  );

  const flagEntries = useMemo(() => {
    const m = state.flags?.flags ?? {};
    return Object.keys(m)
      .sort()
      .map((name) => ({ name, value: m[name] }));
  }, [state.flags]);

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
    <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">
            Admin · Feature Flags
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            灰度发布 / canary 路由控制台 · admin{" "}
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
          <Button size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="h-4 w-4" /> 新增 flag
          </Button>
        </div>
      </header>

      {state.pageError && (
        <div className="flex items-start gap-2 rounded-[var(--radius-lg)] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" /> {state.pageError}
        </div>
      )}

      {state.banner && (
        <div className="rounded-[var(--radius-lg)] border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
          {state.banner}
        </div>
      )}

      <TenantSelector
        tenants={state.tenants}
        selected={state.selectedTenant}
        custom={state.customTenantInput}
        onSelect={(tid) =>
          setState((s) => ({ ...s, selectedTenant: tid, customTenantInput: "" }))
        }
        onCustomChange={(v) =>
          setState((s) => ({ ...s, customTenantInput: v }))
        }
        onSwitchToCustom={() => {
          const v = state.customTenantInput.trim();
          if (!v) return;
          setState((s) => ({
            ...s,
            selectedTenant: v,
            customTenantInput: "",
          }));
        }}
      />

      <FlagsTable
        loading={state.loadingFlags}
        tenantId={state.selectedTenant}
        entries={flagEntries}
        knownFlags={state.knownFlags}
        pendingFlag={pendingFlag}
        onApply={handleApply}
        onDelete={handleDelete}
      />

      <CreateFlagDialog
        open={showCreate}
        onOpenChange={setShowCreate}
        knownFlags={state.knownFlags}
        existingNames={Object.keys(state.flags?.flags ?? {})}
        loading={pendingFlag !== null}
        onCreate={handleCreate}
      />
    </div>
  );
}

// ── tenant 选择器 ──────────────────────────────────────────────────────────


function TenantSelector({
  tenants,
  selected,
  custom,
  onSelect,
  onCustomChange,
  onSwitchToCustom,
}: {
  tenants: TenantSummary[];
  selected: string;
  custom: string;
  onSelect: (tid: string) => void;
  onCustomChange: (v: string) => void;
  onSwitchToCustom: () => void;
}) {
  return (
    <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text)]">Tenant</h2>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            含 ws:{`{wid}`} / u:{`{uid}`} / anon:default 命名空间；列表只列「曾设过
            flag」的 tenant。
          </p>
        </div>
        {tenants.length > 0 && (
          <Badge variant="default">{tenants.length} 个</Badge>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {tenants.length === 0 && (
          <span className="text-xs text-[var(--text-muted)]">
            暂无 tenant 设过 flag。下方输入框输入 tenant_id 然后「新增 flag」
            首次落库即可。
          </span>
        )}
        {tenants.map((t) => (
          <button
            type="button"
            key={t.tenant_id}
            onClick={() => onSelect(t.tenant_id)}
            className={cn(
              "rounded-[var(--radius-md)] border px-3 py-1.5 text-xs transition-colors",
              selected === t.tenant_id
                ? "border-[var(--brand-600)] bg-[var(--brand-100)] text-[var(--brand-700)]"
                : "border-[var(--border)] bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
            )}
          >
            <span className="font-mono">{t.tenant_id}</span>
            <span className="ml-1.5 text-[10px] text-[var(--text-muted)]">
              {t.flag_count} flag{t.flag_count > 1 ? "s" : ""}
            </span>
          </button>
        ))}
      </div>

      <div className="mt-4 flex items-end gap-2">
        <Input
          label="自定义 tenant_id"
          placeholder="ws:abc123 / u:demo-user-001 / anon:default"
          value={custom}
          onChange={(e) => onCustomChange(e.target.value)}
          hint="给从未设过 flag 的 tenant 第一次写值时用；输入后点右侧切换。"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={!custom.trim()}
          onClick={onSwitchToCustom}
        >
          切换
        </Button>
      </div>
    </section>
  );
}

// ── flag 表格 ─────────────────────────────────────────────────────────────


function FlagsTable({
  loading,
  tenantId,
  entries,
  knownFlags,
  pendingFlag,
  onApply,
  onDelete,
}: {
  loading: boolean;
  tenantId: string;
  entries: { name: string; value: FlagValue }[];
  knownFlags: Record<string, string>;
  pendingFlag: string | null;
  onApply: (name: string, value: FlagValue) => void;
  onDelete: (name: string) => void;
}) {
  if (!tenantId) {
    return (
      <section className="rounded-[var(--radius-xl)] border border-dashed border-[var(--border)] bg-[var(--bg-subtle)] p-6 text-center text-sm text-[var(--text-muted)]">
        选一个 tenant 才能看到 flag 列表。
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text)]">
            Flags · <span className="font-mono text-xs">{tenantId}</span>
          </h2>
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            value 形态：<code>{`{"pct":0..100}`}</code> / <code>{`{"enabled":bool}`}</code> /{" "}
            <code>{`{"variant":"v4"}`}</code> / 其它（raw JSON）。
          </p>
        </div>
        {loading && (
          <Loader2 className="h-4 w-4 animate-spin text-[var(--text-muted)]" />
        )}
      </header>

      {entries.length === 0 && !loading && (
        <div className="px-5 py-10 text-center text-sm text-[var(--text-muted)]">
          这个 tenant 还没设任何 flag。点右上「新增 flag」开始。
        </div>
      )}

      <div className="divide-y divide-[var(--border)]">
        {entries.map(({ name, value }) => (
          <FlagRow
            key={name}
            flagName={name}
            value={value}
            description={knownFlags[name]}
            pending={pendingFlag === name}
            onApply={(v) => onApply(name, v)}
            onDelete={() => onDelete(name)}
          />
        ))}
      </div>
    </section>
  );
}

function FlagRow({
  flagName,
  value,
  description,
  pending,
  onApply,
  onDelete,
}: {
  flagName: string;
  value: FlagValue;
  description?: string;
  pending: boolean;
  onApply: (value: FlagValue) => void;
  onDelete: () => void;
}) {
  const initialShape = detectFlagShape(value);
  const [draft, setDraft] = useState<FlagValue>(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(value);

  return (
    <div className="grid grid-cols-1 gap-3 px-5 py-4 md:grid-cols-[1fr_2fr_auto] md:items-center">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-[var(--text)]">
            {flagName}
          </span>
          <Badge
            variant={
              initialShape === "pct"
                ? "primary"
                : initialShape === "enabled"
                ? "success"
                : initialShape === "variant"
                ? "purple"
                : "default"
            }
          >
            {initialShape}
          </Badge>
        </div>
        {description && (
          <p className="mt-1 text-xs text-[var(--text-muted)]">{description}</p>
        )}
      </div>

      <ValueEditor draft={draft} onChange={setDraft} />

      <div className="flex items-center justify-end gap-2">
        <Button
          size="sm"
          disabled={!dirty || pending}
          loading={pending}
          onClick={() => onApply(draft)}
        >
          Apply
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={pending}
          onClick={onDelete}
          className="text-red-500 hover:text-red-600"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ── value 编辑器 ─────────────────────────────────────────────────────────


function ValueEditor({
  draft,
  onChange,
}: {
  draft: FlagValue;
  onChange: (v: FlagValue) => void;
}) {
  const shape = detectFlagShape(draft);

  if (shape === "pct") {
    const pct = clampPct(Number(draft.pct ?? 0));
    return (
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={pct}
          onChange={(e) => onChange({ ...draft, pct: Number(e.target.value) })}
          className="flex-1 accent-[var(--brand-600)]"
        />
        <input
          type="number"
          min={0}
          max={100}
          value={pct}
          onChange={(e) =>
            onChange({ ...draft, pct: clampPct(Number(e.target.value)) })
          }
          className="w-16 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-right text-sm"
        />
        <span className="text-xs text-[var(--text-muted)]">%</span>
      </div>
    );
  }

  if (shape === "enabled") {
    const enabled = Boolean(draft.enabled);
    return (
      <button
        type="button"
        onClick={() => onChange({ ...draft, enabled: !enabled })}
        className={cn(
          "inline-flex h-6 w-11 items-center rounded-full transition-colors",
          enabled ? "bg-[var(--brand-600)]" : "bg-[var(--bg-muted)]"
        )}
        aria-pressed={enabled}
      >
        <span
          className={cn(
            "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
            enabled ? "translate-x-5" : "translate-x-0.5"
          )}
        />
        <span className="ml-3 text-xs text-[var(--text-secondary)]">
          {enabled ? "enabled" : "disabled"}
        </span>
      </button>
    );
  }

  if (shape === "variant") {
    return (
      <Input
        value={String(draft.variant ?? "")}
        onChange={(e) => onChange({ ...draft, variant: e.target.value })}
        placeholder='例：v4 / v3 / off'
        hint="value=off / disabled / 空 视作 disabled"
      />
    );
  }

  // raw JSON 兜底
  const text = JSON.stringify(draft, null, 2);
  return (
    <Textarea
      rows={3}
      value={text}
      onChange={(e) => {
        try {
          const parsed = JSON.parse(e.target.value);
          if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
            onChange(parsed as FlagValue);
          }
        } catch {
          /* keep editing; commit only on Apply via parent */
        }
      }}
      hint="必须是 JSON object；解析失败的中间状态会被 Apply 拒绝。"
    />
  );
}

function clampPct(n: number): number {
  if (Number.isNaN(n)) return 0;
  if (n < 0) return 0;
  if (n > 100) return 100;
  return Math.round(n);
}

// ── 新增 flag dialog ────────────────────────────────────────────────────────


function CreateFlagDialog({
  open,
  onOpenChange,
  knownFlags,
  existingNames,
  loading,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  knownFlags: Record<string, string>;
  existingNames: string[];
  loading: boolean;
  onCreate: (name: string, value: FlagValue) => void;
}) {
  const [name, setName] = useState("");
  const [shape, setShape] = useState<FlagShape>("pct");
  const [pct, setPct] = useState(50);
  const [enabled, setEnabled] = useState(true);
  const [variant, setVariant] = useState("v4");
  const [rawJson, setRawJson] = useState("{}");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setName("");
      setShape("pct");
      setPct(50);
      setEnabled(true);
      setVariant("v4");
      setRawJson("{}");
      setLocalError(null);
    }
  }, [open]);

  const conflict = name && existingNames.includes(name);

  const handleConfirm = () => {
    setLocalError(null);
    const trimmed = name.trim();
    if (!trimmed) {
      setLocalError("flag_name 必填");
      return;
    }
    let value: FlagValue;
    if (shape === "pct") value = { pct: clampPct(pct) };
    else if (shape === "enabled") value = { enabled };
    else if (shape === "variant") value = { variant: variant.trim() };
    else {
      try {
        const parsed = JSON.parse(rawJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setLocalError("raw 必须是 JSON object");
          return;
        }
        value = parsed as FlagValue;
      } catch {
        setLocalError("raw JSON 解析失败");
        return;
      }
    }
    onCreate(trimmed, value);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>新增 / 覆盖 flag</DialogTitle>
          <DialogDescription>
            为当前 tenant upsert 一条 flag。已存在同名 flag 会被覆盖。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--text)]">
              flag_name
            </label>
            <input
              list="known-flags-list"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="art_ipadapter_pct / voice_word_align_v4 ..."
              className="w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-mono"
            />
            <datalist id="known-flags-list">
              {Object.keys(knownFlags).map((k) => (
                <option key={k} value={k} />
              ))}
            </datalist>
            {name && knownFlags[name] && (
              <p className="mt-1 text-xs text-[var(--text-muted)]">
                {knownFlags[name]}
              </p>
            )}
            {conflict && (
              <p className="mt-1 text-xs text-amber-600">
                ⚠ 该 tenant 已存在同名 flag，确认会覆盖原值。
              </p>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--text)]">
              形态
            </label>
            <div className="flex gap-2">
              {(["pct", "enabled", "variant", "raw"] as FlagShape[]).map(
                (s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setShape(s)}
                    className={cn(
                      "rounded-[var(--radius-md)] border px-3 py-1.5 text-xs",
                      shape === s
                        ? "border-[var(--brand-600)] bg-[var(--brand-100)] text-[var(--brand-700)]"
                        : "border-[var(--border)] bg-[var(--bg-subtle)] text-[var(--text-secondary)]"
                    )}
                  >
                    {s}
                  </button>
                )
              )}
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--text)]">
              value
            </label>
            {shape === "pct" && (
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={pct}
                  onChange={(e) => setPct(Number(e.target.value))}
                  className="flex-1 accent-[var(--brand-600)]"
                />
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={pct}
                  onChange={(e) => setPct(clampPct(Number(e.target.value)))}
                  className="w-16 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-right text-sm"
                />
                <span className="text-xs text-[var(--text-muted)]">%</span>
              </div>
            )}
            {shape === "enabled" && (
              <button
                type="button"
                onClick={() => setEnabled(!enabled)}
                className={cn(
                  "inline-flex h-6 w-11 items-center rounded-full transition-colors",
                  enabled ? "bg-[var(--brand-600)]" : "bg-[var(--bg-muted)]"
                )}
                aria-pressed={enabled}
              >
                <span
                  className={cn(
                    "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
                    enabled ? "translate-x-5" : "translate-x-0.5"
                  )}
                />
                <span className="ml-3 text-xs text-[var(--text-secondary)]">
                  {enabled ? "enabled" : "disabled"}
                </span>
              </button>
            )}
            {shape === "variant" && (
              <Input
                value={variant}
                onChange={(e) => setVariant(e.target.value)}
                placeholder="v4 / v3 / off"
              />
            )}
            {shape === "raw" && (
              <Textarea
                rows={4}
                value={rawJson}
                onChange={(e) => setRawJson(e.target.value)}
                hint="任意 JSON object；与 backlog 中后续 flag 形态对齐时用。"
              />
            )}
          </div>

          {localError && (
            <p className="text-sm text-red-600">{localError}</p>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleConfirm} loading={loading}>
            确认 upsert
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
