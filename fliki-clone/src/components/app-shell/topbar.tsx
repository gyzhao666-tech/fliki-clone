"use client";

import { useEffect, useState } from "react";
import { Bell, Search, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator, DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { useTranslations } from "next-intl";
import { Link, useRouter } from "@/i18n/navigation";
import { SearchModal } from "@/components/app-shell/search-modal";
import { LocaleSwitcher } from "@/components/marketing/locale-switcher";
import { api, type UserMe } from "@/lib/api";
import { useIsProjectWorkspace } from "@/hooks/use-project-workspace";

export function Topbar() {
  const isWorkspace = useIsProjectWorkspace();
  const router = useRouter();
  const t = useTranslations("topbar");
  const [user, setUser] = useState<UserMe | null>(null);

  useEffect(() => {
    api<UserMe>("/me")
      .then(setUser)
      .catch(() => router.push("/login"));
  }, [router]);

  function openSearch() {
    document.getElementById("search-trigger")?.click();
  }

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => null);
    router.push("/login");
  }

  const displayName  = user?.name  ?? "";
  const displayEmail = user?.email ?? "";
  const initials = displayName
    ? displayName.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2)
    : "·";

  if (isWorkspace) return null;

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--bg)] px-6">
      <SearchModal />
      {/* Search */}
      <div className="relative hidden sm:flex items-center">
        <Search className="absolute left-3 h-4 w-4 text-[var(--text-muted)] pointer-events-none" />
        <button
          type="button"
          onClick={openSearch}
          className="h-9 w-64 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-subtle)] pl-9 pr-3 text-sm text-[var(--text-muted)] text-left hover:border-[var(--border-strong)] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30"
        >
          {t("searchPlaceholder")}
          <kbd className="float-right text-[10px] border border-[var(--border)] rounded px-1 py-0.5 text-[var(--text-muted)] bg-[var(--bg-muted)]">⌘K</kbd>
        </button>
      </div>
      <div className="sm:hidden" />

      {/* Right actions */}
      <div className="flex items-center gap-2">
        <LocaleSwitcher className="hidden md:flex mr-1" />
        <Button variant="ghost" size="icon" className="relative">
          <Bell className="h-4 w-4" />
          <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-[var(--brand-600)]" />
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="flex items-center gap-2 rounded-[var(--radius-md)] px-2 py-1.5 hover:bg-[var(--bg-muted)] transition-colors cursor-pointer">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--brand-600)] text-white text-xs font-semibold select-none">
                {initials}
              </span>
              <span className="hidden sm:block text-sm font-medium text-[var(--text)]">
                {displayName}
              </span>
              <ChevronDown className="h-3.5 w-3.5 text-[var(--text-muted)]" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel className="font-normal text-xs text-[var(--text-muted)] truncate">{displayEmail}</DropdownMenuLabel>
            {user && (
              <DropdownMenuLabel className="font-normal text-xs text-[var(--text-muted)]">
                {t("plan")}: <span className="capitalize font-medium text-[var(--text)]">{user.plan}</span>
                {" · "}{user.credits.used}/{user.credits.total} {t("min")}
              </DropdownMenuLabel>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/settings/profile">{t("profile")}</Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href="/settings/billing">{t("billing")}</Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-red-500 cursor-pointer" onClick={signOut}>
              {t("signOut")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
