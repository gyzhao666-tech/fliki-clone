"use client";

import { useState } from "react";
import { Wand2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";

const examplePrompts = [
  "A gruff fantasy villain with a deep raspy voice",
  "A warm Southern storyteller, friendly and relaxed",
  "An upbeat Australian fitness coach, energetic",
  "A calm Japanese narrator, thoughtful and precise",
  "A professional British news anchor, authoritative",
  "A cheerful children's storyteller, bright and expressive",
];

export default function VoicesCustomPage() {
  const [prompt, setPrompt] = useState("");
  const [voiceName, setVoiceName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(false);

  function handleCreate() {
    if (!prompt) return;
    setCreating(true);
    setTimeout(() => {
      setCreating(false);
      setCreated(true);
    }, 1800);
  }

  return (
    <div className="p-7 max-w-none">
      {/* Header banner */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-6 mb-7 flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[var(--radius-xl)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]">
          <Wand2 className="h-7 w-7" />
        </div>
        <div className="flex-1">
          <h1 className="font-bold text-lg text-[var(--text)] mb-1">Generate custom unique voices</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Describe the age, accent, tone, or character and create a new voice in seconds — then generate any number of voiceovers using just text.
          </p>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-7">
        {/* Create panel */}
        <div className="flex flex-col gap-5">
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-2">
              Voice name (optional)
            </label>
            <input
              value={voiceName}
              onChange={(e) => setVoiceName(e.target.value)}
              placeholder="e.g. Gruff Villain, Warm Coach…"
              className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
            />
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] block mb-2">
              Describe the voice
            </label>
            <Textarea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe age, accent, tone, character… e.g. 'A warm 40-year-old Southern storyteller with a relaxed, unhurried pace'"
            />
          </div>

          <Button
            className="gap-2 w-fit"
            disabled={!prompt || creating}
            onClick={handleCreate}
          >
            {creating ? (
              <>
                <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                Creating…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" />
                Create custom voice
              </>
            )}
          </Button>

          {created && (
            <div className="rounded-[var(--radius-lg)] border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              ✅ Voice created! You can now use it in your projects.
            </div>
          )}
        </div>

        {/* Example prompts */}
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">
            Try these examples
          </p>
          <div className="flex flex-col gap-2">
            {examplePrompts.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => setPrompt(ex)}
                className="text-left rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--text-secondary)] hover:border-[var(--brand-600)]/40 hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-all"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
