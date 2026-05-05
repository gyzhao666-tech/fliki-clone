"use client";

import { Check, ChevronsUpDown, Loader2 } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCurrentWorkspace } from "@/hooks/use-current-workspace";
import type { WorkspaceRole } from "@/lib/workspaces";
import { cn } from "@/lib/utils";

/**
 * Track-30 · sidebar 顶部的 workspace 切换 dropdown。
 *
 * 设计取舍
 * --------
 * - 用既有 shadcn `<DropdownMenu>`（项目里没有 `<Select>`，dropdown 已是其它
 *   sidebar 入口的同款交互）；keyboard / Esc / 外点关闭 / a11y 由 radix 兜底
 * - role badge 颜色按 spec：admin 紫 / editor sky / viewer slate；颜色用 tailwind
 *   原生 token（不经 `var(--brand-*)`）保证视觉对比稳定
 * - loading 状态只渲一个静态占位（不做 skeleton 闪烁）；空 workspace 列表渲
 *   "无 workspace" 占位字（不会发生，因 `_get_or_create_workspace` 兜底，但 v1
 *   不指望该 fallback 永久存在）
 * - 与 admin links 段（行 127-145）严格分离：本组件只在 logo 段下方挂载
 */

const ROLE_LABEL: Record<WorkspaceRole, string> = {
  admin: "Admin",
  editor: "Editor",
  viewer: "Viewer",
};

const ROLE_BADGE_CLASS: Record<WorkspaceRole, string> = {
  admin: "bg-purple-100 text-purple-700",
  editor: "bg-sky-100 text-sky-700",
  viewer: "bg-slate-100 text-slate-600",
};

function RoleBadge({ role }: { role: WorkspaceRole }) {
  return (
    <span
      className={cn(
        "ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        ROLE_BADGE_CLASS[role]
      )}
    >
      {ROLE_LABEL[role]}
    </span>
  );
}

export function WorkspaceSelector() {
  const { current, list, switchTo, loading } = useCurrentWorkspace();

  const triggerLabel = (() => {
    if (loading && !current) return "Loading…";
    if (!current) return "No workspace";
    return current.name;
  })();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-muted)] px-3 py-2 text-left text-sm font-semibold text-[var(--text)]",
          "hover:bg-[var(--surface)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30",
          "disabled:cursor-not-allowed disabled:opacity-60"
        )}
        disabled={loading && list.length === 0}
        aria-label="Switch workspace"
      >
        <span className="flex min-w-0 items-center gap-2">
          {loading && !current ? (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[var(--text-muted)]" />
          ) : null}
          <span className="truncate">{triggerLabel}</span>
          {current ? <RoleBadge role={current.role} /> : null}
        </span>
        <ChevronsUpDown className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="start"
        sideOffset={6}
        className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-56"
      >
        <DropdownMenuLabel>Switch workspace</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {list.length === 0 ? (
          <DropdownMenuItem disabled>No workspaces yet</DropdownMenuItem>
        ) : (
          list.map((ws) => {
            const active = current?.id === ws.id;
            return (
              <DropdownMenuItem
                key={ws.id}
                onSelect={() => switchTo(ws.id)}
                className="flex items-center justify-between gap-2"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <Check
                    className={cn(
                      "h-4 w-4 shrink-0",
                      active
                        ? "text-[var(--brand-600)]"
                        : "text-transparent"
                    )}
                  />
                  <span className="truncate">{ws.name}</span>
                </span>
                <RoleBadge role={ws.role} />
              </DropdownMenuItem>
            );
          })
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
