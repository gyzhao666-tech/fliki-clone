"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

const tabs = [
  { href: "/settings/profile", labelKey: "profile" as const },
  { href: "/settings/billing", labelKey: "billing" as const },
];

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const t = useTranslations("settingsPage");

  return (
    <div className="max-w-3xl mx-auto p-6 w-full">
      <h1 className="text-2xl font-bold text-[var(--text)] mb-1">{t("title")}</h1>
      <p className="text-sm text-[var(--text-secondary)] mb-6">{t("subtitle")}</p>

      <div className="flex gap-1 p-1 rounded-[var(--radius-lg)] bg-[var(--bg-muted)] border border-[var(--border)] w-fit mb-8">
        {tabs.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                "px-4 py-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors",
                active
                  ? "bg-[var(--surface)] text-[var(--text)] shadow-sm"
                  : "text-[var(--text-secondary)] hover:text-[var(--text)]"
              )}
            >
              {t(tab.labelKey)}
            </Link>
          );
        })}
      </div>

      {children}
    </div>
  );
}
