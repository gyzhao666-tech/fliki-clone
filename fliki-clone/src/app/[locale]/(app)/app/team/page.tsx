"use client";

import { Mail, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const members = [
  { email: "jane@example.com", role: "Owner", status: "Active" },
  { email: "alex@example.com", role: "Editor", status: "Active" },
];

export default function TeamPage() {
  return (
    <div className="p-7">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Team</h1>
          <p className="text-sm text-[var(--text-secondary)]">
            Invite collaborators and manage seats for your workspace.
          </p>
        </div>
        <Button className="gap-1.5">
          <Mail className="h-4 w-4" /> Invite member
        </Button>
      </div>

      <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] bg-[var(--bg-subtle)] text-left text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
              <th className="px-4 py-3">Member</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 w-12" />
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.email} className="border-b border-[var(--border)] last:border-0">
                <td className="px-4 py-3 text-[var(--text)]">{m.email}</td>
                <td className="px-4 py-3 text-[var(--text-secondary)]">{m.role}</td>
                <td className="px-4 py-3">
                  <Badge variant="success">{m.status}</Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <button type="button" className="p-1 rounded hover:bg-[var(--bg-muted)]">
                    <MoreHorizontal className="h-4 w-4 text-[var(--text-muted)]" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
