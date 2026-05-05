"use client";

import { usePathname } from "@/i18n/navigation";
import { isProjectWorkspacePath } from "@/lib/app-path";

export function useIsProjectWorkspace(): boolean {
  const pathname = usePathname() ?? "";
  return isProjectWorkspacePath(pathname);
}
