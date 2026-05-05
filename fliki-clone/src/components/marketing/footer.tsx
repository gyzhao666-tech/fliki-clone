"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { Zap } from "lucide-react";
import { BRAND } from "@/lib/brand";

export function Footer() {
  const t = useTranslations("marketing.footer");
  const columns = t.raw("columns") as { title: string; links: string[] }[];

  return (
    <footer className="border-t border-[var(--border)] bg-[var(--bg-subtle)]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-5">
          <div className="col-span-2 md:col-span-1">
            <Link href="/" className="flex items-center gap-2 font-bold text-[var(--text)]">
              <span className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] bg-[var(--brand-600)]">
                <Zap className="h-4 w-4 text-white" />
              </span>
              {BRAND.name}
            </Link>
            <p className="mt-3 text-sm text-[var(--text-muted)]">{t("brandTagline")}</p>
          </div>

          {columns.map((col) => (
            <div key={col.title}>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
                {col.title}
              </h4>
              <ul className="flex flex-col gap-2">
                {col.links.map((link) => (
                  <li key={link}>
                    <Link
                      href="#"
                      className="text-sm text-[var(--text-secondary)] hover:text-[var(--text)] transition-colors"
                    >
                      {link}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 border-t border-[var(--border)] pt-6 flex flex-col sm:flex-row justify-between items-center gap-3">
          <p className="text-xs text-[var(--text-muted)]" suppressHydrationWarning>
            {t("copyright", { year: new Date().getFullYear() })}
          </p>
          <p className="text-xs text-[var(--text-muted)]">{t("madeWith")}</p>
        </div>
      </div>
    </footer>
  );
}
