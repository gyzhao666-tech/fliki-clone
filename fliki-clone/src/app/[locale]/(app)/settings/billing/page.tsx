"use client";

import { Link } from "@/i18n/navigation";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

const plans = [
  { name: "Free", price: "$0", credits: "5 min / month", features: ["HD export", "Basic voices"] },
  { name: "Standard", price: "$28", credits: "180 min / month", features: ["1080p", "Premium voices", "No watermark"], highlight: true },
  { name: "Premium", price: "$88", credits: "600 min / month", features: ["Everything in Standard", "Voice clone", "Priority support"] },
];

export default function SettingsBillingPage() {
  return (
    <div className="space-y-8">
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-2">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">Current plan</h2>
            <p className="text-sm text-[var(--text-secondary)] mt-1">You are on the Free plan.</p>
          </div>
          <Badge variant="default">Free</Badge>
        </div>
        <div className="mt-4 h-2 rounded-full bg-[var(--bg-muted)] overflow-hidden">
          <div className="h-full w-3/5 rounded-full bg-[var(--brand-600)]" />
        </div>
        <p className="text-xs text-[var(--text-muted)] mt-2">3 of 5 minutes used this billing period</p>

        <Dialog>
          <DialogTrigger asChild>
            <Button className="mt-6">Upgrade plan</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Choose a plan</DialogTitle>
            </DialogHeader>
            <div className="grid sm:grid-cols-3 gap-4 pt-2">
              {plans.map((p) => (
                <div
                  key={p.name}
                  className={`rounded-[var(--radius-lg)] border p-4 flex flex-col ${
                    p.highlight ? "border-[var(--brand-600)] bg-[var(--brand-600)]/5" : "border-[var(--border)]"
                  }`}
                >
                  <p className="font-semibold text-[var(--text)]">{p.name}</p>
                  <p className="text-2xl font-bold text-[var(--text)] mt-2">
                    {p.price}
                    <span className="text-sm font-normal text-[var(--text-muted)]">/mo</span>
                  </p>
                  <p className="text-xs text-[var(--text-secondary)] mt-1">{p.credits}</p>
                  <ul className="mt-4 space-y-2 flex-1">
                    {p.features.map((f) => (
                      <li key={f} className="flex gap-2 text-xs text-[var(--text-secondary)]">
                        <Check className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                        {f}
                      </li>
                    ))}
                  </ul>
                  <Button size="sm" className="mt-4 w-full" variant={p.highlight ? "primary" : "outline"}>
                    Select
                  </Button>
                </div>
              ))}
            </div>
          </DialogContent>
        </Dialog>
      </section>

      <p className="text-sm text-[var(--text-secondary)]">
        Need an invoice or custom team pricing?{" "}
        <Link href="/enterprise" className="text-[var(--brand-600)] hover:underline">
          Contact sales
        </Link>
      </p>
    </div>
  );
}
