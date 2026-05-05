export const dynamic = "force-dynamic";

import { AppShell } from "@/components/app-shell/app-shell";
import { UserEventsListener } from "@/components/user-events-listener";
import { WorkspaceProvider } from "@/hooks/use-current-workspace";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <AppShell>
        <UserEventsListener />
        {children}
      </AppShell>
    </WorkspaceProvider>
  );
}
