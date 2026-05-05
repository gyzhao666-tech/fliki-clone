"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { DlqItemOut, DlqStatus, ListDlqParams, listDlq } from "@/lib/dlq";

/**
 * useDlq
 * ──────
 * 拉 `GET /api/dlq?status=&run_id=&limit=`，并提供 reload 触发器与可选 polling。
 *
 * 设计：
 * - filter / runId / enabled 任一变化都会重拉
 * - retry / discard 后调 `reload()` 同步最新状态
 * - 失败静默（保留旧数据），不打扰主流程；error 暴露给 UI 用于角标提示
 * - `pollIntervalMs` > 0 时按间隔轮询；用于 worker 模式下捕捉新入库的死信
 */
export interface UseDlqResult {
  items: DlqItemOut[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export interface UseDlqOpts extends ListDlqParams {
  enabled?: boolean;
  pollIntervalMs?: number;
}

export function useDlq(opts: UseDlqOpts = {}): UseDlqResult {
  const { enabled = true, pollIntervalMs = 0, status, runId, limit } = opts;
  const [items, setItems] = useState<DlqItemOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);

  const fetchOnce = useCallback(async () => {
    if (!enabled) {
      setItems([]);
      return;
    }
    inflight.current?.abort();
    const ctrl = new AbortController();
    inflight.current = ctrl;
    setLoading(true);
    try {
      const next = await listDlq({ status, runId, limit });
      if (!ctrl.signal.aborted) {
        setItems(next);
        setError(null);
      }
    } catch (err) {
      if (ctrl.signal.aborted) return;
      const message = err instanceof ApiError ? `API ${err.status}` : "网络错误";
      setError(message);
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, [enabled, status, runId, limit]);

  useEffect(() => {
    fetchOnce();
    return () => inflight.current?.abort();
  }, [fetchOnce]);

  useEffect(() => {
    if (!enabled || pollIntervalMs <= 0) return;
    const t = setInterval(fetchOnce, pollIntervalMs);
    return () => clearInterval(t);
  }, [enabled, pollIntervalMs, fetchOnce]);

  return { items, loading, error, reload: fetchOnce };
}

export type { DlqStatus };
