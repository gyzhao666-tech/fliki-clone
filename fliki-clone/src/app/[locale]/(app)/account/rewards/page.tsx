"use client";

import { useState } from "react";
import { Copy, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const socialPlatforms = [
  { label: "YouTube",   color: "text-red-500" },
  { label: "TikTok",    color: "text-[var(--text)]" },
  { label: "Instagram", color: "text-pink-500" },
  { label: "Twitter",   color: "text-sky-500" },
  { label: "LinkedIn",  color: "text-blue-600" },
  { label: "Facebook",  color: "text-blue-500" },
];

export default function AccountRewardsPage() {
  const [copied, setCopied] = useState(false);

  function copyLink() {
    navigator.clipboard.writeText("https://fliki.ai?referral=demo-user");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-5">
        <h2 className="font-bold text-base text-[var(--text)] mb-1">Want to increase your credits? 🚀</h2>
        <p className="text-sm text-[var(--text-secondary)]">Earn up to 18 minutes of credits by spreading a word about Fliki!</p>
      </div>

      {/* Share videos */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--text)]">🎥 Share videos created with Fliki on socials</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">Earn 2 credits for each video you share</p>
          </div>
          <Badge variant="success">+2 credits</Badge>
        </div>
        <div className="flex flex-wrap gap-2 mb-4">
          {socialPlatforms.map(({ label, color }) => (
            <span key={label} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-[var(--border)] text-xs font-medium ${color}`}>
              {label}
            </span>
          ))}
        </div>
        <Button size="sm" variant="outline">Start submitting</Button>
      </section>

      {/* Reviews */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold text-[var(--text)]">⭐️ Give genuine reviews about Fliki</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">Earn 1 credit for each genuine review on G2, Trustpilot, Capterra…</p>
          </div>
          <Badge variant="success">+1 credit</Badge>
        </div>
        <Button size="sm" variant="outline">Start submitting</Button>
      </section>

      {/* Copy link button placeholder */}
      <button
        type="button"
        onClick={copyLink}
        className="hidden"
        aria-hidden
      />
    </div>
  );
}
