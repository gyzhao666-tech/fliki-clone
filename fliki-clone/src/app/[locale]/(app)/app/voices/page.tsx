"use client";

import { useState } from "react";
import { Mic, Play, Heart, Search, Globe, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Link } from "@/i18n/navigation";

const languages = ["All", "English", "Spanish", "Chinese", "French", "German", "Japanese", "Hindi", "Arabic"];

const voices = [
  { id: "v1", name: "Aria", style: "Expressive", lang: "English (US)", accent: "American", tags: ["Narration", "Commercial"] },
  { id: "v2", name: "Marcus", style: "Warm", lang: "English (UK)", accent: "British", tags: ["Podcast", "Corporate"] },
  { id: "v3", name: "Sofia", style: "Upbeat", lang: "Spanish (ES)", accent: "Castilian", tags: ["Social", "Promo"] },
  { id: "v4", name: "Kenji", style: "Calm", lang: "Japanese", accent: "Tokyo", tags: ["Explainer", "E-learning"] },
  { id: "v5", name: "Priya", style: "Professional", lang: "Hindi", accent: "Standard", tags: ["Corporate", "Documentary"] },
  { id: "v6", name: "Elise", style: "Bright", lang: "French (FR)", accent: "Parisian", tags: ["Narration", "Social"] },
  { id: "v7", name: "Chen", style: "Neutral", lang: "Chinese (Mandarin)", accent: "Beijing", tags: ["Explainer", "Narration"] },
  { id: "v8", name: "Amara", style: "Storyteller", lang: "Arabic", accent: "Modern Standard", tags: ["Documentary", "Educational"] },
];

const avatarColors = [
  "bg-indigo-400", "bg-violet-400", "bg-teal-400", "bg-amber-400",
  "bg-rose-400", "bg-sky-400", "bg-emerald-400", "bg-orange-400",
];

export default function VoicesPage() {
  const [q, setQ] = useState("");
  const [selectedLang, setSelectedLang] = useState("All");
  const [playing, setPlaying] = useState<string | null>(null);
  const [liked, setLiked] = useState<Set<string>>(new Set());

  const filtered = voices.filter((v) => {
    const matchQ = v.name.toLowerCase().includes(q.toLowerCase()) ||
      v.lang.toLowerCase().includes(q.toLowerCase());
    const matchLang = selectedLang === "All" || v.lang.toLowerCase().startsWith(selectedLang.toLowerCase());
    return matchQ && matchLang;
  });

  return (
    <div className="p-7 max-w-none">
      {/* Clone voice banner */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-5 mb-6 flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[var(--radius-xl)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]">
          <Mic className="h-6 w-6" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="font-bold text-sm text-[var(--text)] mb-0.5">Clone your voice</h2>
          <p className="text-xs text-[var(--text-secondary)]">
            Record two minutes of your voice, then generate any number of voiceovers in your own voice using just text.
          </p>
        </div>
        <Button size="sm" className="gap-1.5 shrink-0" asChild>
          <Link href="/app/voices">
            <Mic className="h-3.5 w-3.5" /> Clone voice
          </Link>
        </Button>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {/* Search */}
        <div className="relative flex-1 min-w-48 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--text-muted)] pointer-events-none" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name or language…"
            className="w-full h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] pl-8 pr-3 text-xs text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
          />
        </div>

        {/* Language filter pills */}
        <div className="flex flex-wrap gap-1.5">
          {languages.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => setSelectedLang(l)}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1 rounded-full border text-[11px] font-medium transition-all",
                selectedLang === l
                  ? "border-[var(--brand-600)] bg-[var(--brand-600)] text-white"
                  : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
              )}
            >
              {l === "All" && <Globe className="h-3 w-3" />}
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Count */}
      <p className="text-xs text-[var(--text-muted)] mb-3">
        Showing {filtered.length} of {voices.length} voices
      </p>

      {/* Voice list */}
      <div className="flex flex-col gap-1.5">
        {filtered.map((v, i) => {
          const isPlaying = playing === v.id;
          const isLiked = liked.has(v.id);
          return (
            <div
              key={v.id}
              className="group flex items-center gap-3 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 hover:border-[var(--brand-600)]/30 hover:bg-[var(--surface-hover)] transition-all"
            >
              {/* Play */}
              <button
                type="button"
                onClick={() => setPlaying(isPlaying ? null : v.id)}
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors",
                  isPlaying
                    ? "bg-[var(--brand-600)] text-white"
                    : "bg-[var(--bg-muted)] text-[var(--text-secondary)] hover:bg-[var(--brand-600)]/10 hover:text-[var(--brand-600)]"
                )}
              >
                {isPlaying ? (
                  <span className="flex gap-0.5">
                    {[1, 2, 3].map((b) => (
                      <span
                        key={b}
                        className="w-0.5 h-3 bg-white rounded-full animate-bounce"
                        style={{ animationDelay: `${b * 0.1}s` }}
                      />
                    ))}
                  </span>
                ) : (
                  <Play className="h-3.5 w-3.5 ml-0.5" />
                )}
              </button>

              {/* Avatar */}
              <div className={`${avatarColors[i % avatarColors.length]} flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white text-xs font-bold`}>
                {v.name[0]}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--text)]">{v.name}</span>
                  <span className="text-xs text-[var(--text-muted)]">· {v.style}</span>
                </div>
                <div className="flex items-center gap-1 mt-0.5">
                  <Globe className="h-3 w-3 text-[var(--text-muted)]" />
                  <span className="text-[11px] text-[var(--text-muted)]">{v.lang}</span>
                </div>
              </div>

              {/* Tags */}
              <div className="hidden sm:flex gap-1 shrink-0">
                {v.tags.map((t) => (
                  <Badge key={t} variant="default" className="text-[10px] px-1.5 py-0">{t}</Badge>
                ))}
              </div>

              {/* Favourite */}
              <button
                type="button"
                onClick={() => setLiked((prev) => {
                  const next = new Set(prev);
                  next.has(v.id) ? next.delete(v.id) : next.add(v.id);
                  return next;
                })}
                className={cn(
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors opacity-0 group-hover:opacity-100",
                  isLiked
                    ? "text-rose-500 opacity-100"
                    : "text-[var(--text-muted)] hover:text-rose-400"
                )}
              >
                <Heart className={cn("h-3.5 w-3.5", isLiked && "fill-rose-500")} />
              </button>
            </div>
          );
        })}
      </div>

      {filtered.length === 0 && (
        <p className="py-12 text-center text-sm text-[var(--text-muted)]">No voices matching your filter.</p>
      )}
    </div>
  );
}
