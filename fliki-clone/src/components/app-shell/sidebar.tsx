"use client";

import { useEffect, useState } from "react";
import {
  AudioLines,
  Bot,
  Boxes,
  BriefcaseBusiness,
  Clapperboard,
  FileVideo,
  FolderOpen,
  Home,
  Library,
  LineChart,
  Megaphone,
  Palette,
  PlaySquare,
  ShieldCheck,
  Users,
  Zap,
} from "lucide-react";
import { Link, usePathname } from "@/i18n/navigation";
import { getAdminMe } from "@/lib/admin-flags";
import { cn } from "@/lib/utils";

const primaryNav = [
  { href: "/app/files", label: "Files", icon: FolderOpen },
  { href: "/app/create", label: "Create", icon: FileVideo },
  { href: "/app/templates", label: "Templates", icon: Library },
  { href: "/app/exports", label: "Exports", icon: PlaySquare },
  { href: "/app/playground", label: "Playground", icon: Bot },
];

const libraryNav = [
  { href: "/app/assets", label: "Assets", icon: Boxes },
  { href: "/app/voices", label: "Voices", icon: AudioLines },
  { href: "/app/characters", label: "Characters", icon: Clapperboard },
  { href: "/app/brand-kits", label: "Brand kits", icon: Palette },
  { href: "/app/team", label: "Team", icon: Users },
  { href: "/app/automation", label: "Automation", icon: BriefcaseBusiness },
  { href: "/app/series", label: "Series", icon: Megaphone },
];

function NavLink({
  href,
  label,
  icon: Icon,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  const pathname = usePathname() ?? "";
  const normalized = pathname.replace(/^\/(en|zh)(?=\/)/, "");
  const active = normalized === href || normalized.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-4 rounded-[var(--radius-lg)] px-5 py-3.5 text-[17px] font-semibold transition-colors",
        active
          ? "bg-[var(--brand-600)]/10 text-[var(--brand-600)]"
          : "text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text)]"
      )}
    >
      <Icon className="h-6 w-6 shrink-0" />
      <span className="truncate">{label}</span>
    </Link>
  );
}

/**
 * 探测当前用户是否 admin（命中 ADMIN_EMAILS 白名单）。
 *
 * 设计：onMount 单次轻量探测；非 admin / 错误一律静默隐藏入口（不污染开发台）。
 * 本页 + 路由本身都有 admin 鉴权兜底，前端隐藏只是降噪 UX。
 */
function useIsAdmin(): boolean {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getAdminMe()
      .then((me) => {
        if (!cancelled) setIsAdmin(Boolean(me.is_admin));
      })
      .catch(() => {
        if (!cancelled) setIsAdmin(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return isAdmin;
}

export function Sidebar() {
  const isAdmin = useIsAdmin();
  return (
    <aside className="hidden h-screen w-80 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] md:flex">
      <div className="flex h-20 shrink-0 items-center gap-4 border-b border-[var(--border)] px-7 py-5">
        <span className="flex h-11 w-11 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--brand-600)]">
          <Zap className="h-6 w-6 text-white" />
        </span>
        <span className="text-xl font-extrabold text-[var(--text)]">Fliki</span>
      </div>

      <nav className="flex flex-1 flex-col gap-8 overflow-y-auto px-5 py-6">
        <div className="space-y-2">
          <NavLink href="/app/files" label="Home" icon={Home} />
          {primaryNav.slice(1).map((item) => (
            <NavLink key={item.href} {...item} />
          ))}
        </div>

        <div>
          <p className="px-5 pb-3 text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
            Library
          </p>
          <div className="space-y-2">
            {libraryNav.map((item) => (
              <NavLink key={item.href} {...item} />
            ))}
          </div>
        </div>

        {isAdmin && (
          <div>
            <p className="px-5 pb-3 text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Admin
            </p>
            <div className="space-y-2">
              <NavLink
                href="/app/admin/feature-flags"
                label="Feature Flags"
                icon={ShieldCheck}
              />
              <NavLink
                href="/app/admin/metrics"
                label="Metrics"
                icon={LineChart}
              />
            </div>
          </div>
        )}
      </nav>

      <div className="border-t border-[var(--border)] p-3">
        <Link
          href="/pricing"
          className="flex flex-col gap-1 rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-[var(--brand-600)]/5 p-3 text-sm"
        >
          <span className="font-semibold text-[var(--text)]">Upgrade plan</span>
          <span className="text-xs text-[var(--text-muted)]">Unlock more video minutes.</span>
        </Link>
      </div>
    </aside>
  );
}
