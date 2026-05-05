"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  listMyWorkspaces,
  type WorkspaceMembership,
} from "@/lib/workspaces";

/**
 * Track-30 · Workspace 上下文 + 选择器。
 *
 * 设计取舍
 * --------
 * - **localStorage 持久化**（key `fliki:current-workspace-id`）：跨 tab / 刷新都不
 *   重置选择；server-render 时 fallback 到列表第一个（`current === null` ⇒ 还没加载）
 * - **首次加载策略**：listMyWorkspaces 完成后，若 localStorage 里的 id 仍在 list 里
 *   就用它；否则用 `list[0]`；空列表时 `current=null`（sidebar 会绘出"无 workspace"
 *   占位）
 * - **switch 副作用**：state + localStorage 写一次；不强制重新 fetch 全局 queries（让
 *   各 page 决定要不要响应；本批 follow-up 会扩 emit 自定义事件）
 * - **Provider 架构**：Context 为单例，`(app)/layout.tsx` 在最外层 wrap 一次；
 *   所有子页面 / sidebar / 其它组件共享同一份状态，避免每个组件各拉一次 API
 * - **错误处理**：listMyWorkspaces 失败 → list=[] + loading=false + 不抛；UI 自然
 *   展示空 dropdown（与 admin-flags.getAdminMe 一致：网络错不阻塞渲染）
 *
 * 已知边界
 * --------
 * - 切换 workspace 后，page-level 的 react-query / SSE 订阅 **不会** 自动 refetch；
 *   v1 让用户手动刷新页面，或后续 follow-up 让 hook emit `workspace-changed` 事件
 *   让各 page invalidate 自己的 cache
 * - 本 hook 不强制把 workspace_id 传给后端（后端 `_get_or_create_workspace` 仍按
 *   owner 兜底）；多租户隔离 API guard 是 follow-up Track 的事
 */

const STORAGE_KEY = "fliki:current-workspace-id";

interface WorkspaceContextValue {
  /** 当前选中的 workspace；初次加载完成前为 null。 */
  current: WorkspaceMembership | null;
  /** 用户所有可见 workspace（own + 受邀）；按 created_at ASC。 */
  list: WorkspaceMembership[];
  /** 切到某个 workspace；id 不在 list 里则 noop（防御性）。 */
  switchTo: (id: string) => void;
  /** 是否还在拉首屏列表。 */
  loading: boolean;
  /** 错误信息（拉列表失败）；null 表示 OK 或还没拉过。 */
  error: string | null;
  /** 重新拉一次列表（保留当前选择，若仍在新列表里）。 */
  refresh: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

function readStoredId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredId(id: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (id) {
      window.localStorage.setItem(STORAGE_KEY, id);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    /* SSR / quota / private-mode 兜底 */
  }
}

function pickInitialWorkspace(
  list: WorkspaceMembership[],
  storedId: string | null
): WorkspaceMembership | null {
  if (list.length === 0) return null;
  if (storedId) {
    const hit = list.find((w) => w.id === storedId);
    if (hit) return hit;
  }
  return list[0];
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<WorkspaceMembership[]>([]);
  const [current, setCurrent] = useState<WorkspaceMembership | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const out = await listMyWorkspaces();
      if (cancelledRef.current) return;
      setList(out.workspaces);
      setCurrent((prev) => {
        if (prev) {
          const hit = out.workspaces.find((w) => w.id === prev.id);
          if (hit) return hit;
        }
        return pickInitialWorkspace(out.workspaces, readStoredId());
      });
    } catch (err) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "load workspaces failed");
      setList([]);
      setCurrent(null);
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;
    void load();
    return () => {
      cancelledRef.current = true;
    };
  }, [load]);

  const switchTo = useCallback(
    (id: string) => {
      const hit = list.find((w) => w.id === id);
      if (!hit) return; // 防御：id 不在 list 里 → noop（避免选到失效 workspace）
      writeStoredId(id);
      setCurrent(hit);
    },
    [list]
  );

  const refresh = useCallback(async () => {
    await load();
  }, [load]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ current, list, switchTo, loading, error, refresh }),
    [current, list, switchTo, loading, error, refresh]
  );

  // 用 createElement 避免把文件改成 .tsx；本 hook 文件以 .ts 结尾保持仓库
  // 既有 hook 命名风格（参考 use-user-events.ts / use-current-role.ts）
  return createElement(WorkspaceContext.Provider, { value }, children);
}

/**
 * 获取当前 workspace 上下文。
 *
 * 必须包在 `<WorkspaceProvider>` 子树内（`(app)/layout.tsx` 已 wrap）；
 * 没 wrap 时抛 Error 而非返默认值——避免静默失败让组件以为没 workspace。
 */
export function useCurrentWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error(
      "useCurrentWorkspace must be used inside <WorkspaceProvider>"
    );
  }
  return ctx;
}
