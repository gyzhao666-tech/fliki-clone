"use client";

import { useState } from "react";
import { Copy, Check, Users } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AccountReferralsPage() {
  const referralLink = "https://fliki.ai?referral=demo-user-abc123";
  const [copied, setCopied] = useState(false);

  function copyLink() {
    navigator.clipboard.writeText(referralLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-6">
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-5">
        <h2 className="font-bold text-base text-[var(--text)] mb-1">Referral program ❤️</h2>
        <p className="text-sm text-[var(--text-secondary)]">
          Invite your friends to Fliki and earn up to 120 credits 🤯😍!
        </p>
      </div>

      {/* How it works */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-4">How it works</h2>
        <ol className="space-y-3 text-sm text-[var(--text-secondary)]">
          <li className="flex gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--brand-600)]/10 text-xs font-bold text-[var(--brand-600)]">1</span>
            <span><strong className="text-[var(--text)]">Share your referral link</strong> — copy your unique link below and share with friends.</span>
          </li>
          <li className="flex gap-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--brand-600)]/10 text-xs font-bold text-[var(--brand-600)]">2</span>
            <span><strong className="text-[var(--text)]">Your friend signs up</strong> — for each friend that signs up using your link, you&apos;ll receive 2 credits!</span>
          </li>
        </ol>
      </section>

      {/* Referral link */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-3">Your referral link</h2>
        <div className="flex items-center gap-2">
          <input
            readOnly
            value={referralLink}
            className="flex-1 h-10 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-subtle)] px-3 text-sm text-[var(--text-secondary)] focus:outline-none"
          />
          <Button size="sm" variant="outline" className="gap-1.5 shrink-0" onClick={copyLink}>
            {copied ? <><Check className="h-3.5 w-3.5 text-emerald-500" /> Copied!</> : <><Copy className="h-3.5 w-3.5" /> Copy link</>}
          </Button>
        </div>
      </section>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4">
        {[
          { label: "Total referrals", value: "0" },
          { label: "Total credits earned", value: "0" },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-5 flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">{label}</span>
            <span className="text-3xl font-bold text-[var(--text)]">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
