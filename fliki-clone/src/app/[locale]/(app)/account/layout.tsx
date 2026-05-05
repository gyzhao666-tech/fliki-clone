"use client";

import { useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { cn } from "@/lib/utils";

const tabs = [
  { href: "/account/profile", labelKey: "profile" as const },
  { href: "/account/rewards", labelKey: "rewards" as const },
  { href: "/account/referrals", labelKey: "referrals" as const },
  { href: "/account/affiliate", labelKey: "affiliate" as const },
];

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const t = useTranslations("accountPage");
  return (
    <div className="p-7 max-w-3xl">
      <h1 className="text-xl font-bold text-[var(--text)] mb-1">{t("title")}</h1>
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
