"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function SettingsProfilePage() {
  const [name, setName] = useState("Jane Doe");
  const [email, setEmail] = useState("jane@example.com");

  return (
    <div className="space-y-8">
      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-base font-semibold text-[var(--text)] mb-4">Profile</h2>
        <div className="flex flex-col sm:flex-row gap-6">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full bg-[var(--brand-600)] text-white text-2xl font-bold">
            J
          </div>
          <div className="flex-1 space-y-4 max-w-md">
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] block mb-1.5">Display name</label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] block mb-1.5">Email</label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <Button>Save changes</Button>
          </div>
        </div>
      </section>

      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-base font-semibold text-[var(--text)] mb-2">Password</h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">Update your password to keep your account secure.</p>
        <Button variant="outline">Change password</Button>
      </section>
    </div>
  );
}
