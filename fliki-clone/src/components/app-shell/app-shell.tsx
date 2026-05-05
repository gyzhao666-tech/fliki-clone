"use client";

import { Sidebar } from "@/components/app-shell/sidebar";
import { Topbar } from "@/components/app-shell/topbar";
import { Toaster } from "sonner";
import { useIsProjectWorkspace } from "@/hooks/use-project-workspace";

export function AppShell({ children }: { children: React.ReactNode }) {
  const isWorkspace = useIsProjectWorkspace();

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg)]">
      <Sidebar />
      <div className="flex flex-1 flex-col min-w-0 min-h-0">
        {!isWorkspace && <Topbar />}
        <main
          className={
            isWorkspace
              ? "flex-1 min-h-0 overflow-hidden flex flex-col"
              : "flex-1 min-h-0 overflow-y-auto"
          }
        >
          {children}
        </main>
      </div>
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            fontFamily: "var(--font-nunito-sans), 'Nunito Sans', sans-serif",
            fontSize: "13px",
          },
        }}
      />
    </div>
  );
}
