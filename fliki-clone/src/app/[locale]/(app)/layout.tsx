export const dynamic = "force-dynamic";

import { AppShell } from "@/components/app-shell/app-shell";
import { UserEventsListener } from "@/components/user-events-listener";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppShell>
      <UserEventsListener />
      {children}
    </AppShell>
  );
}
