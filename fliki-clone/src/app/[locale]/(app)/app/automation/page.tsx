"use client";

import { Link } from "@/i18n/navigation";
import { Workflow, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AutomationPage() {
  return (
    <div className="p-7">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-[var(--text)]">Automation</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Connect Fliki to your stack with webhooks, RSS, and scheduled runs.
        </p>
      </div>

      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-8 flex flex-col sm:flex-row gap-6 items-start">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[var(--radius-xl)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]">
          <Workflow className="h-7 w-7" />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-semibold text-[var(--text)] mb-2">Workflow builder</h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            Automation is available on Team and Enterprise plans. Upgrade to turn blog posts, sheets, and feeds into
            video pipelines.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link href="/enterprise">
                Contact sales <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href="/pricing">View pricing</Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
