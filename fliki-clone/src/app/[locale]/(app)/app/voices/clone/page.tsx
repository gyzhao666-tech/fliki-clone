"use client";

import { useState } from "react";
import { Mic, UploadCloud, CheckCircle2, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const steps = [
  {
    id: 1,
    title: "Record your voice",
    desc: "Record at least 2 minutes of natural speech in a quiet room. Read the sample text below, or speak freely.",
  },
  {
    id: 2,
    title: "Upload the recording",
    desc: "Upload a clear .mp3 or .wav file. No background music, no reverb.",
  },
  {
    id: 3,
    title: "Name your clone",
    desc: "Give your voice clone a name so you can find it quickly in your projects.",
  },
  {
    id: 4,
    title: "Generate",
    desc: "We'll process your recording and create a realistic AI clone. Usually takes under 5 minutes.",
  },
];

const sampleText = `The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs. How razorback jumping frogs can level six piqued gymnasts. The five boxing wizards jump quickly. Sphinx of black quartz, judge my vow.`;

export default function VoicesClonePage() {
  const [step, setStep] = useState(1);
  const [cloneName, setCloneName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [processing, setProcessing] = useState(false);
  const [done, setDone] = useState(false);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.[0]) setFile(e.target.files[0]);
  }

  function handleGenerate() {
    if (!cloneName) return;
    setProcessing(true);
    setTimeout(() => { setProcessing(false); setDone(true); }, 2500);
  }

  return (
    <div className="p-7 max-w-none">
      {/* Banner */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-6 mb-8 flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[var(--radius-xl)] bg-[var(--brand-600)]/10 text-[var(--brand-600)]">
          <Mic className="h-7 w-7" />
        </div>
        <div>
          <h1 className="font-bold text-lg text-[var(--text)] mb-1">Clone your voice</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Record two minutes of your voice, then generate any number of voiceovers in your own voice using just text.
          </p>
        </div>
      </div>

      <div className="grid lg:grid-cols-5 gap-8">
        {/* Steps sidebar */}
        <div className="lg:col-span-2 flex flex-col gap-3">
          {steps.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => !done && setStep(s.id)}
              className={cn(
                "flex items-start gap-3 rounded-[var(--radius-xl)] border p-4 text-left transition-all",
                step === s.id && !done
                  ? "border-[var(--brand-600)] bg-[var(--brand-600)]/5"
                  : done || s.id < step
                  ? "border-emerald-200 bg-emerald-50/50"
                  : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
              )}
            >
              <span className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold mt-0.5",
                done || s.id < step
                  ? "bg-emerald-500 text-white"
                  : step === s.id
                  ? "bg-[var(--brand-600)] text-white"
                  : "bg-[var(--bg-muted)] text-[var(--text-muted)]"
              )}>
                {done || s.id < step ? <CheckCircle2 className="h-4 w-4" /> : s.id}
              </span>
              <div>
                <p className={cn("text-sm font-semibold mb-0.5", step === s.id ? "text-[var(--brand-600)]" : "text-[var(--text)]")}>{s.title}</p>
                <p className="text-xs text-[var(--text-muted)]">{s.desc}</p>
              </div>
            </button>
          ))}
        </div>

        {/* Main panel */}
        <div className="lg:col-span-3">
          {done ? (
            <div className="rounded-[var(--radius-xl)] border border-emerald-200 bg-emerald-50 p-8 flex flex-col items-center text-center gap-3">
              <CheckCircle2 className="h-12 w-12 text-emerald-500" />
              <h2 className="text-lg font-bold text-[var(--text)]">Voice clone created!</h2>
              <p className="text-sm text-[var(--text-secondary)] max-w-sm">
                &ldquo;{cloneName}&rdquo; is ready. Open any project and select it from the Voice menu.
              </p>
            </div>
          ) : (
            <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 flex flex-col gap-6">
              {/* Step 1: Sample text */}
              {step === 1 && (
                <>
                  <div>
                    <p className="text-sm font-semibold text-[var(--text)] mb-2">Sample text to read aloud</p>
                    <div className="rounded-[var(--radius-lg)] bg-[var(--bg-subtle)] border border-[var(--border)] p-4 text-sm text-[var(--text-secondary)] leading-relaxed">
                      {sampleText}
                    </div>
                    <p className="text-xs text-[var(--text-muted)] mt-2">Record at least 2 minutes. You can read this multiple times or speak naturally.</p>
                  </div>
                  <Button className="gap-2 w-fit" onClick={() => setStep(2)}>
                    <Mic className="h-4 w-4" /> Ready to upload <ChevronRight className="h-4 w-4" />
                  </Button>
                </>
              )}

              {/* Step 2: Upload */}
              {step === 2 && (
                <>
                  <div>
                    <p className="text-sm font-semibold text-[var(--text)] mb-3">Upload your recording</p>
                    <label className={cn(
                      "flex flex-col items-center justify-center gap-3 rounded-[var(--radius-xl)] border-2 border-dashed p-10 cursor-pointer transition-colors",
                      file ? "border-emerald-400 bg-emerald-50" : "border-[var(--border)] hover:border-[var(--brand-600)]/50 hover:bg-[var(--brand-600)]/3"
                    )}>
                      <input type="file" accept=".mp3,.wav,.m4a" className="sr-only" onChange={handleFile} />
                      {file ? (
                        <>
                          <CheckCircle2 className="h-8 w-8 text-emerald-500" />
                          <p className="text-sm font-semibold text-emerald-700">{file.name}</p>
                          <p className="text-xs text-emerald-600">Click to replace</p>
                        </>
                      ) : (
                        <>
                          <UploadCloud className="h-8 w-8 text-[var(--text-muted)]" />
                          <p className="text-sm font-semibold text-[var(--text)]">Click or drag to upload</p>
                          <p className="text-xs text-[var(--text-muted)]">.mp3 · .wav · .m4a — max 100 MB</p>
                        </>
                      )}
                    </label>
                  </div>
                  <Button className="gap-2 w-fit" disabled={!file} onClick={() => setStep(3)}>
                    Continue <ChevronRight className="h-4 w-4" />
                  </Button>
                </>
              )}

              {/* Step 3: Name */}
              {step === 3 && (
                <>
                  <div>
                    <label className="text-sm font-semibold text-[var(--text)] block mb-2">Name your voice clone</label>
                    <input
                      value={cloneName}
                      onChange={(e) => setCloneName(e.target.value)}
                      placeholder="e.g. My Voice, Guangyuan's Voice…"
                      className="h-10 w-full max-w-sm rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-subtle)] px-3 text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
                    />
                  </div>
                  <Button className="gap-2 w-fit" disabled={!cloneName} onClick={() => setStep(4)}>
                    Continue <ChevronRight className="h-4 w-4" />
                  </Button>
                </>
              )}

              {/* Step 4: Generate */}
              {step === 4 && (
                <>
                  <div className="space-y-2">
                    <p className="text-sm font-semibold text-[var(--text)]">Ready to create &ldquo;{cloneName}&rdquo;</p>
                    <p className="text-sm text-[var(--text-secondary)]">We&apos;ll process your recording and generate the voice clone. Usually takes under 5 minutes.</p>
                  </div>
                  <Button className="gap-2 w-fit" onClick={handleGenerate} disabled={processing}>
                    {processing ? (
                      <>
                        <span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                        Processing…
                      </>
                    ) : (
                      <>
                        <Mic className="h-4 w-4" /> Clone voice
                      </>
                    )}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
