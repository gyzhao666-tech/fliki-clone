"use client";

import { Link } from "@/i18n/navigation";
import { Clapperboard, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";

const mockSeries = [
  { id: "sr1", title: "Weekly tips", episodes: 12, updated: "3 days ago" },
  { id: "sr2", title: "Product tutorials", episodes: 6, updated: "1 week ago" },
];

export default function SeriesPage() {
  return (
    <div className="p-7">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Series</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Group episodes into a series for consistent branding and publishing.
          </p>
        </div>
        <Button className="gap-1.5">
          <Plus className="h-4 w-4" /> New series
        </Button>
      </div>

      <div className="grid gap-4">
        {mockSeries.map((s) => (
          <Link
            key={s.id}
            href={`/app/files`}
            className="flex items-center gap-4 rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-4 hover:border-[var(--brand-600)]/40 transition-colors"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]">
              <Clapperboard className="h-6 w-6" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-[var(--text)]">{s.title}</p>
              <p className="text-sm text-[var(--text-muted)]">
                {s.episodes} episodes · Updated {s.updated}
              </p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
