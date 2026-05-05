"use client";

import { Link } from "@/i18n/navigation";
import { Zap } from "lucide-react";

export function MarketingTopnav() {
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--border)] bg-[var(--bg)]/85 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 font-bold text-[var(--text)]">
          <span className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] bg-[var(--brand-600)]">
            <Zap className="h-4 w-4 text-white" />
          </span>
          Fliki
        </Link>
        <nav className="hidden items-center gap-7 text-sm font-medium text-[var(--text-secondary)] md:flex">
          <Link href="/features" className="hover:text-[var(--text)]">Features</Link>
          <Link href="/pricing" className="hover:text-[var(--text)]">Pricing</Link>
          <Link href="/enterprise" className="hover:text-[var(--text)]">Enterprise</Link>
          <Link href="/about" className="hover:text-[var(--text)]">About</Link>
        </nav>
        <div className="flex items-center gap-3">
          <Link href="/login" className="hidden text-sm font-semibold text-[var(--text-secondary)] hover:text-[var(--text)] sm:inline">
            Login
          </Link>
          <Link href="/signup" className="rounded-full bg-[var(--brand-600)] px-5 py-2.5 text-sm font-bold text-white hover:bg-[var(--brand-700)]">
            Start free
          </Link>
        </div>
      </div>
    </header>
  );
}
