"use client";

import { useEffect, useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import { Link } from "@/i18n/navigation";

const shortcuts = [
  { href: "/app/create", label: "Create new video" },
  { href: "/app/files", label: "Files" },
  { href: "/app/templates", label: "Templates" },
  { href: "/app/voices", label: "Voices" },
  { href: "/app/assets", label: "Assets" },
  { href: "/settings/profile", label: "Profile settings" },
  { href: "/settings/billing", label: "Billing" },
];

export function SearchModal() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return shortcuts;
    return shortcuts.filter((item) => item.label.toLowerCase().includes(q));
  }, [query]);

  return (
    <>
      <button id="search-trigger" type="button" className="sr-only" onClick={() => setOpen(true)}>
        Open search
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/35 px-4 pt-24">
          <div className="w-full max-w-xl overflow-hidden rounded-[var(--radius-2xl)] border border-[var(--border)] bg-[var(--surface)] shadow-xl">
            <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3">
              <Search className="h-4 w-4 text-[var(--text-muted)]" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search pages..."
                className="h-9 flex-1 bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-muted)]"
              />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-[var(--radius-md)] p-1 text-[var(--text-muted)] hover:bg-[var(--bg-muted)] hover:text-[var(--text)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-80 overflow-y-auto p-2">
              {results.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setOpen(false)}
                  className="block rounded-[var(--radius-md)] px-3 py-2 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text)]"
                >
                  {item.label}
                </Link>
              ))}
              {results.length === 0 && (
                <p className="px-3 py-8 text-center text-sm text-[var(--text-muted)]">No results found.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
