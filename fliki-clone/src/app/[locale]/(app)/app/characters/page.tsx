"use client";

import { Plus, UserCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

const mockChars = [
  { id: "c1", name: "Alex — Presenter", style: "Realistic" },
  { id: "c2", name: "Maya — Host", style: "Anime" },
];

export default function CharactersPage() {
  return (
    <div className="p-7">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Characters</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Save and reuse AI characters across scenes for consistent storytelling.
          </p>
        </div>
        <Button className="gap-1.5">
          <Plus className="h-4 w-4" /> New character
        </Button>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        {mockChars.map((c) => (
          <div
            key={c.id}
            className="flex gap-4 rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-4"
          >
            <div className="h-20 w-20 rounded-[var(--radius-lg)] bg-[var(--bg-muted)] flex items-center justify-center shrink-0">
              <UserCircle className="h-10 w-10 text-[var(--text-muted)]" />
            </div>
            <div>
              <p className="font-semibold text-[var(--text)]">{c.name}</p>
              <p className="text-sm text-[var(--text-muted)]">{c.style}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
