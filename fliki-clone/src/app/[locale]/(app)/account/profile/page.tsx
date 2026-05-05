"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";

export default function AccountProfilePage() {
  const [name,  setName]  = useState("Jane Doe");
  const [email] = useState("demo@fliki.ai");
  const [ytId,  setYtId]  = useState("");

  const [emailNotif, setEmailNotif] = useState({
    export: true,
    series: false,
    team: false,
    collab: false,
  });

  return (
    <div className="space-y-6">
      {/* Basic details */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-4">Basic details</h2>
        <div className="space-y-4 max-w-md">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1.5">Email</label>
            <input
              value={email}
              disabled
              className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-subtle)] px-3 text-sm text-[var(--text-muted)] cursor-not-allowed"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1.5">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">YouTube channel ID(s)</label>
            <p className="text-xs text-[var(--text-muted)] mb-1.5">Add your YouTube channel ID to prevent copyright claims.</p>
            <input
              value={ytId}
              onChange={(e) => setYtId(e.target.value)}
              placeholder="UC…"
              className="h-10 w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-600)]/30 focus:border-[var(--brand-600)]"
            />
          </div>
          <Button size="sm">Save</Button>
        </div>
      </section>

      {/* Change password */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-2">Change password</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">Keep your account secure with a strong password.</p>
        <Button variant="outline" size="sm">Change password</Button>
      </section>

      {/* Email notifications */}
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-4">Email notifications</h2>
        <div className="space-y-3">
          {[
            { key: "export" as const,  label: "Export status",             desc: "Get notified whenever your file is ready for download." },
            { key: "series" as const,  label: "Series updates",            desc: "Get notified about the series status." },
            { key: "team" as const,    label: "Team updates",              desc: "Get notified about the team and members updates." },
            { key: "collab" as const,  label: "Collaboration updates",     desc: "Get notified about team file creation and sharing." },
          ].map(({ key, label, desc }) => (
            <label key={key} className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={emailNotif[key]}
                onChange={() => setEmailNotif((p) => ({ ...p, [key]: !p[key] }))}
                className="mt-0.5 h-4 w-4 rounded border-[var(--border)] text-[var(--brand-600)] accent-[var(--brand-600)]"
              />
              <div>
                <p className="text-sm font-medium text-[var(--text)]">{label}</p>
                <p className="text-xs text-[var(--text-muted)]">{desc}</p>
              </div>
            </label>
          ))}
        </div>
        <Button size="sm" className="mt-4">Save</Button>
      </section>

      {/* Danger zone */}
      <section className="rounded-[var(--radius-xl)] border border-red-200 bg-red-50/50 p-6">
        <h2 className="text-sm font-semibold text-red-700 mb-2">Danger zone</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">Reset account data — this action cannot be undone.</p>
        <Button variant="destructive" size="sm">Reset account data</Button>
      </section>
    </div>
  );
}
