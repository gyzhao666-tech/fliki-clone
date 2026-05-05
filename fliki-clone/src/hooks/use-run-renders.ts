"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { RenderOut, getRunRenders } from "@/lib/production";

/**
 * useRunRenders
 * ─────────────
 * 拉 `GET /api/production/runs/{run_id}/renders`，并提供 reload 触发器。
 *
 * 设计：
 * - `runId` / `enabled` 变化时自动拉一次
 * - 调用方在 SSE 收到 edit step 状态变化后调 `reload()` 主动重拉
 * - persist 在 SSE publish 之前同步执行（runner 顺序保证），所以重拉一定能拿到最新数据
 * - 失败静默（保留旧数据），不打扰主流程
 */
export interface UseRunRendersResult {
  renders: RenderOut[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useRunRenders(
  runId: string | null,
  opts?: { enabled?: boolean }
): UseRunRendersResult {
  const enabled = opts?.enabled ?? true;
  const [renders, setRenders] = useState<RenderOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);

  const fetchOnce = useCallback(async () => {
    if (!runId || !enabled) {
      setRenders([]);
      return;
    }
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setLoading(true);
    try {
      const next = await getRunRenders(runId);
      if (!ctrl.signal.aborted) {
        setRenders(next);
        setError(null);
      }
    } catch (err) {
      if (ctrl.signal.aborted) return;
      const message = err instanceof ApiError ? `API ${err.status}` : "网络错误";
      setError(message);
      // 不清空 renders：保留上一轮成功结果
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [runId, enabled]);

  useEffect(() => {
    fetchOnce();
    return () => inflight.current?.abort();
  }, [fetchOnce]);

  return { renders, loading, error, reload: fetchOnce };
}
