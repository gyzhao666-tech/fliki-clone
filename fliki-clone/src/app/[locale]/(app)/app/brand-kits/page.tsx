"use client";

import { Plus, Palette } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function BrandKitsPage() {
  return (
    <div className="p-7">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Brand kits</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Store logos, colors, and fonts for on-brand videos.
          </p>
        </div>
        <Button className="gap-1.5">
          <Plus className="h-4 w-4" /> New brand kit
        </Button>
      </div>

      <div className="rounded-[var(--radius-xl)] border border-dashed border-[var(--border)] bg-[var(--bg-subtle)] p-12 text-center">
        <Palette className="h-10 w-10 text-[var(--text-muted)] mx-auto mb-3" />
        <p className="text-sm text-[var(--text-secondary)] mb-4">You haven&apos;t created a brand kit yet.</p>
        <Button variant="outline" size="sm">
          Create brand kit
        </Button>
      </div>
    </div>
  );
}
