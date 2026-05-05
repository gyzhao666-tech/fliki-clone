"use client";

import { useState } from "react";
import { Link } from "@/i18n/navigation";
import { Sparkles, Image, Video, Music, FilePlus, RefreshCw, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/* ─── Model list ─── */
const imageModels = [
  { id: "z-turbo", name: "Z Image Turbo", credits: "0.05", locked: false },
  { id: "flux-klein", name: "Flux 2 Klein", credits: "0.05", locked: false },
  { id: "flux-pro", name: "FLUX Pro", credits: "0.2", locked: true },
  { id: "flux-2", name: "FLUX 2", credits: "0.5", locked: true },
  { id: "hi-dream", name: "Hi-Dream Fast", credits: "0.1", locked: true },
  { id: "gpt-image", name: "GPT Image 1.5", credits: "1.0", locked: true },
];

const styles = ["Cinematic", "Anime", "Realistic", "3D", "Comic", "Watercolor"];

const samplePrompts = [
  "A woman in a red slip dress against a dark city backdrop",
  "Hokusai's Great Wave reimagined in neon colors",
  "A lone samurai in full traditional armor, misty forest",
  "Miniature city built inside a teacup, macro photography",
  "Double exposure portrait of a woman and a moonlit forest",
  "35mm photo of a floating island above clouds at golden hour",
];

/* ─── Mock history items ─── */
const historyItems = samplePrompts.map((p, i) => ({
  id: String(i),
  prompt: p,
  color: ["bg-slate-400", "bg-indigo-400", "bg-violet-400", "bg-sky-400", "bg-teal-400", "bg-amber-400"][i % 6],
}));

/* ─── Aspect ratio pill ─── */
const ratios = ["9:16", "1:1", "16:9"] as const;

/* ─── Page ─── */
export default function PlaygroundPage() {
  const [tab, setTab] = useState<"image" | "video" | "music">("image");
  const [prompt, setPrompt] = useState("");
  const [selectedModel, setSelectedModel] = useState(imageModels[0].id);
  const [selectedRatio, setSelectedRatio] = useState<string>("9:16");
  const [selectedStyle, setSelectedStyle] = useState("Cinematic");
  const [showAllModels, setShowAllModels] = useState(false);

  const visibleModels = showAllModels ? imageModels : imageModels.slice(0, 3);

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Left panel ── */}
      <div className="w-64 shrink-0 border-r border-[var(--border)] bg-[var(--bg-subtle)] flex flex-col overflow-y-auto">
        {/* Tabs */}
        <div className="flex border-b border-[var(--border)]">
          {(["image", "video", "music"] as const).map((t) => {
            const Icon = t === "image" ? Image : t === "video" ? Video : Music;
            return (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={cn(
                  "flex-1 flex flex-col items-center gap-0.5 py-3 text-[10px] font-semibold uppercase tracking-wider transition-colors",
                  tab === t
                    ? "text-[var(--brand-600)] border-b-2 border-[var(--brand-600)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text)]"
                )}
              >
                <Icon className="h-4 w-4" />
                {t}
              </button>
            );
          })}
        </div>

        {/* New file button */}
        <div className="p-3 border-b border-[var(--border)]">
          <Button variant="outline" size="sm" className="w-full gap-1.5 text-xs" asChild>
            <Link href="/app/create"><FilePlus className="h-3.5 w-3.5" /> New file</Link>
          </Button>
        </div>

        {tab === "image" && (
          <div className="p-3 flex flex-col gap-4">
            {/* Prompt */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">
                Prompt
              </label>
              <Textarea
                rows={4}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe the image you want to generate…"
                className="text-xs"
              />
            </div>

            {/* Model */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">
                Model
              </label>
              <div className="flex flex-col gap-1">
                {visibleModels.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    disabled={m.locked}
                    onClick={() => !m.locked && setSelectedModel(m.id)}
                    className={cn(
                      "text-left rounded-[var(--radius-md)] border px-2.5 py-1.5 text-xs transition-all",
                      m.locked
                        ? "border-[var(--border)] text-[var(--text-muted)] opacity-50 cursor-not-allowed"
                        : selectedModel === m.id
                        ? "border-[var(--brand-600)] bg-[var(--brand-600)]/8 text-[var(--text)]"
                        : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
                    )}
                  >
                    <span className="font-medium">{m.name}</span>
                    <span className="ml-1 text-[var(--text-muted)]">({m.credits} credits)</span>
                    {m.locked && <span className="ml-1 text-[10px]">🔒</span>}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setShowAllModels((v) => !v)}
                className="mt-1 flex items-center gap-1 text-[10px] text-[var(--brand-600)] hover:underline"
              >
                <ChevronDown className={cn("h-3 w-3 transition-transform", showAllModels && "rotate-180")} />
                {showAllModels ? "Show less" : `+${imageModels.length - 3} more`}
              </button>
            </div>

            {/* Aspect Ratio */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">
                Aspect ratio
              </label>
              <div className="flex gap-1.5">
                {ratios.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setSelectedRatio(r)}
                    className={cn(
                      "flex-1 py-1.5 rounded-[var(--radius-md)] border text-xs font-medium transition-all",
                      selectedRatio === r
                        ? "border-[var(--brand-600)] bg-[var(--brand-600)]/8 text-[var(--brand-600)]"
                        : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
                    )}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>

            {/* Style */}
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-1.5">
                Style
              </label>
              <div className="flex flex-wrap gap-1.5">
                {styles.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSelectedStyle(s)}
                    className={cn(
                      "px-2.5 py-1 rounded-full border text-[11px] font-medium transition-all",
                      selectedStyle === s
                        ? "border-[var(--brand-600)] bg-[var(--brand-600)] text-white"
                        : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--brand-600)]/50"
                    )}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Generate */}
            <Button className="w-full gap-1.5">
              <Sparkles className="h-3.5 w-3.5" /> Generate
            </Button>
          </div>
        )}

        {tab !== "image" && (
          <div className="flex-1 flex items-center justify-center p-6 text-center">
            <p className="text-xs text-[var(--text-muted)]">
              {tab === "video" ? "Video generation" : "Music generation"} available on paid plans.
            </p>
          </div>
        )}
      </div>

      {/* ── Right: history grid ── */}
      <div className="flex-1 min-w-0 overflow-y-auto bg-[var(--bg)]">
        {tab === "image" ? (
          <div className="p-5">
            {/* Sample prompts */}
            {historyItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 text-center">
                <p className="text-sm text-[var(--text-muted)]">No history yet</p>
                <p className="text-xs text-[var(--text-muted)] mt-1">Generate an image to see it here</p>
              </div>
            ) : (
              <>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
                  Try these samples
                </p>
                <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
                  {historyItems.map((item) => (
                    <div
                      key={item.id}
                      className="group relative cursor-pointer rounded-[var(--radius-lg)] overflow-hidden"
                    >
                      {/* placeholder image */}
                      <div
                        className={`${item.color} aspect-square opacity-70 group-hover:opacity-100 transition-opacity`}
                      />
                      {/* hover overlay */}
                      <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-end">
                        <div className="w-full translate-y-full group-hover:translate-y-0 transition-transform p-1.5">
                          <button
                            type="button"
                            className="flex items-center gap-1 w-full justify-center text-[10px] font-semibold text-white bg-black/40 rounded py-1 backdrop-blur-sm hover:bg-black/60"
                          >
                            <RefreshCw className="h-3 w-3" /> Recreate
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* no history */}
                <div className="mt-8 rounded-[var(--radius-xl)] border border-dashed border-[var(--border)] bg-[var(--surface)] p-8 text-center">
                  <p className="text-xs text-[var(--text-muted)]">No history yet — your generated images will appear here.</p>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <p className="text-sm text-[var(--text-muted)]">Select a tab to begin.</p>
          </div>
        )}
      </div>
    </div>
  );
}
