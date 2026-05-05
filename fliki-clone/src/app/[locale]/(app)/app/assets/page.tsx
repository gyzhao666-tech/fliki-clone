"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";

const categories = ["All", "Stock video", "Images", "Music", "Icons"];

export default function AssetsPage() {
  const [cat, setCat] = useState("All");

  return (
    <div className="p-7 max-w-none">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[var(--text)]">Asset library</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          Stock media and graphics to use across your projects.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 mb-6">
        {categories.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCat(c)}
            className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
              cat === c
                ? "bg-[var(--brand-600)] text-white"
                : "bg-[var(--bg-muted)] text-[var(--text-secondary)] hover:text-[var(--text)]"
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <div className="mb-6 max-w-md">
        <Input
          placeholder="Search assets…"
          leftIcon={<Search className="h-4 w-4" />}
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 10 }).map((_, i) => (
          <div
            key={i}
            className="aspect-video rounded-[var(--radius-lg)] bg-gradient-to-br from-slate-600/40 to-slate-800/60 border border-[var(--border)] hover:ring-2 hover:ring-[var(--brand-600)]/40 transition-all cursor-pointer"
          />
        ))}
      </div>
    </div>
  );
}
