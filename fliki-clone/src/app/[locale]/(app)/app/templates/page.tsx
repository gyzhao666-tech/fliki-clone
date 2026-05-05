"use client";

import { useEffect, useMemo, useState } from "react";
import { Link } from "@/i18n/navigation";
import { Play, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Template = {
  id: string;
  title: string;
  category: string;
  thumbnail_url: string | null;
  duration: string | null;
  lang: string;
  uses_count: number;
  config_json?: {
    mode_name?: string;
    best_for?: string[];
    required_inputs?: { key: string; label: string }[];
    scenes?: { id: string; name: string; duration: number }[];
  } | null;
};

const PLACEHOLDER_COLORS = [
  "#3b82f6", "#a855f7", "#10b981", "#ec4899",
  "#f59e0b", "#ef4444", "#64748b", "#8b5cf6",
];

function placeholderColor(index: number) {
  return PLACEHOLDER_COLORS[index % PLACEHOLDER_COLORS.length];
}

function TemplateCard({ template, index }: { template: Template; index: number }) {
  return (
    <div className="group rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden hover:shadow-lg hover:border-[var(--brand-600)]/40 transition-all cursor-pointer">
      <div className="relative">
        {template.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={template.thumbnail_url}
            alt={template.title}
            className="aspect-[9/16] w-full object-cover opacity-80 group-hover:opacity-100 transition-opacity"
          />
        ) : (
          <div
            className="aspect-[9/16] opacity-80 group-hover:opacity-100 transition-opacity"
            style={{ backgroundColor: placeholderColor(index) }}
          />
        )}
        {/* duration badge */}
        <span className="absolute bottom-2 right-2 text-[10px] font-medium bg-black/60 text-white px-1.5 py-0.5 rounded">
          {template.duration ?? "—"}
        </span>
        {/* hover overlay */}
        <div className="absolute inset-0 flex flex-col items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/25 gap-2">
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-white/90 text-gray-900 hover:bg-white shadow transition-colors"
          >
            <Play className="h-4 w-4 ml-0.5" />
          </button>
          <Link
            href="/app/create"
            className="px-3 py-1 rounded-full text-[11px] font-semibold bg-[var(--brand-600)] text-white hover:bg-[var(--brand-700)] transition-colors shadow"
          >
            Use template
          </Link>
        </div>
      </div>
      <div className="p-2.5">
        <p className="text-[12px] font-semibold text-[var(--text)] leading-tight truncate mb-1">{template.title}</p>
        <div className="flex items-center justify-between">
          <Badge variant="default" className="text-[10px] px-1.5 py-0">{template.category}</Badge>
          <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
            <Users className="h-3 w-3" />
            {(template.uses_count / 1000).toFixed(1)}k
          </span>
        </div>
        {template.config_json?.mode_name && (
          <p className="mt-1.5 truncate text-[10px] font-medium text-[var(--brand-600)]">
            {template.config_json.mode_name}
          </p>
        )}
      </div>
    </div>
  );
}

export default function TemplatesPage() {
  const [activeCategory, setActiveCategory] = useState("All");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        setLoading(true);
        const data = await api<Template[]>("/templates");
        if (!mounted) return;
        setTemplates(data);
      } catch {
        if (!mounted) return;
        setError("Failed to load templates");
      } finally {
        if (mounted) setLoading(false);
      }
    })();

    return () => {
      mounted = false;
    };
  }, []);

  const categories = useMemo(
    () => ["All", ...Array.from(new Set(templates.map((t) => t.category)))],
    [templates]
  );

  const filtered = activeCategory === "All"
    ? templates
    : templates.filter((t) => t.category === activeCategory);

  return (
    <div className="p-7">
      {/* Header */}
      <div className="mb-5">
        <h1 className="text-xl font-bold text-[var(--text)]">Templates</h1>
        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
          Start with a professionally designed template · {templates.length} available
        </p>
      </div>

      {/* Category filter */}
      <div className="flex gap-1.5 flex-wrap mb-5 overflow-x-auto pb-1">
        {categories.map((cat) => (
          <button
            key={cat}
            type="button"
            onClick={() => setActiveCategory(cat)}
            className={cn(
              "px-3 py-1.5 rounded-full text-[11px] font-semibold transition-all border whitespace-nowrap",
              activeCategory === cat
                ? "bg-[var(--brand-600)] text-white border-[var(--brand-600)]"
                : "bg-[var(--surface)] text-[var(--text-secondary)] border-[var(--border)] hover:border-[var(--border-strong)] hover:text-[var(--text)]"
            )}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* Grid */}
      {loading ? (
        <div className="text-sm text-[var(--text-secondary)]">Loading templates...</div>
      ) : error ? (
        <div className="text-sm text-red-500">{error}</div>
      ) : (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7 gap-3">
          {filtered.map((t, i) => <TemplateCard key={t.id} template={t} index={i} />)}
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="py-20 text-center">
          <p className="text-[var(--text-secondary)]">No templates in this category yet.</p>
        </div>
      )}
    </div>
  );
}
