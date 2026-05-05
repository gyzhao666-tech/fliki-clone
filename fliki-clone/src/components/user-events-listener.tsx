"use client";

import { useUserEvents } from "@/hooks/use-user-events";

/**
 * Track-25：把 `useUserEvents` 包成无渲染 client component，让 server component
 * `(app)/layout.tsx` 一行 `<UserEventsListener />` 就能挂上全局 quota_exceeded /
 * bucket_full toast 监听，不需要把整个 layout 切成 client。
 */
export function UserEventsListener() {
  useUserEvents();
  return null;
}
