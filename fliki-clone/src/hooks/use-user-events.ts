"use client";

import { useEffect, useRef } from "react";

import { feedback } from "@/lib/feedback";

/**
 * useUserEvents
 * ─────────────
 * Track-25：订阅 `/api/pipelines/user-events` 全局 SSE，把 `quota_exceeded` /
 * `bucket_full` 事件映射成 `feedback.error` / `feedback.warning` toast。
 *
 * 协议（与 `app/routers/pipelines.py::user_events_stream` 对齐）：
 *   - id: <stream_id>                    每条事件带 redis Stream id
 *   - event: snapshot                    连接首条 quota + bucket 全量（不弹 toast）
 *   - event: quota_exceeded              月度额度不足 → error toast
 *   - event: bucket_full                 provider 并发到上限 → warning toast
 *   - :ping                              心跳；EventSource 自动忽略
 *
 * 行为：
 *   - 浏览器原生 EventSource 携带 cookie 鉴权 + 自动断网重连（带 Last-Event-ID）
 *   - onerror 不主动 close（只要 readyState 仍是 CONNECTING），让浏览器原生续传机会
 *   - 同一类事件 1.5s 内去重（防止短时间多条 quota_exceeded 刷屏）
 *   - 没有 enabled gate：layout 挂载即生效（用户登录后才走到 (app) 路由）
 */

type SnapshotPayload = {
  user_id?: string;
  tenant_id?: string;
  tenant_plan?: string;
  monthly_limit_usd?: number;
  current_period_usage_usd?: number;
  remaining_usd?: number;
  concurrent_max?: number;
  active_runs?: number;
  provider_buckets?: Array<{
    provider_name: string;
    current_in_flight: number;
    max_concurrent: number;
    remaining: number;
    utilization_pct: number;
  }>;
};

type QuotaExceededPayload = {
  tenant_id?: string;
  kind?: string;
  message?: string;
  attempted_cost?: number;
  monthly_limit?: number;
  current_usage?: number;
};

type BucketFullPayload = {
  tenant_id?: string;
  kind?: string;
  provider_name?: string;
  message?: string;
  current_in_flight?: number | null;
  max_concurrent?: number | null;
};

const TOAST_DEDUP_WINDOW_MS = 1500;

function backendBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ?? "http://localhost:8000"
  );
}

export function useUserEvents() {
  const lastSnapshotRef = useRef<SnapshotPayload | null>(null);
  // key=event_type+provider_name → ts；防短时间内同事件刷屏
  const lastToastAtRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = `${backendBaseUrl()}/api/pipelines/user-events`;
    const es = new EventSource(url, { withCredentials: true });

    const shouldEmit = (key: string) => {
      const now = Date.now();
      const last = lastToastAtRef.current.get(key) ?? 0;
      if (now - last < TOAST_DEDUP_WINDOW_MS) return false;
      lastToastAtRef.current.set(key, now);
      return true;
    };

    es.addEventListener("snapshot", (ev) => {
      try {
        lastSnapshotRef.current = JSON.parse(
          (ev as MessageEvent).data
        ) as SnapshotPayload;
      } catch {
        /* ignore malformed snapshot */
      }
    });

    es.addEventListener("quota_exceeded", (ev) => {
      let payload: QuotaExceededPayload = {};
      try {
        payload = JSON.parse((ev as MessageEvent).data) as QuotaExceededPayload;
      } catch {
        /* ignore */
      }
      if (!shouldEmit("quota_exceeded")) return;
      const remaining = computeRemaining(lastSnapshotRef.current, payload);
      const remainingFmt = remaining != null ? remaining.toFixed(4) : "0.0000";
      feedback.error(`月度额度不足，剩余 $${remainingFmt}`, {
        description:
          payload.message ??
          (payload.attempted_cost != null
            ? `本次需要 $${payload.attempted_cost.toFixed(4)}`
            : undefined),
      });
    });

    es.addEventListener("bucket_full", (ev) => {
      let payload: BucketFullPayload = {};
      try {
        payload = JSON.parse((ev as MessageEvent).data) as BucketFullPayload;
      } catch {
        /* ignore */
      }
      const provider = payload.provider_name ?? "unknown";
      if (!shouldEmit(`bucket_full:${provider}`)) return;
      const detail =
        payload.current_in_flight != null && payload.max_concurrent != null
          ? `${payload.current_in_flight}/${payload.max_concurrent} 已占满`
          : undefined;
      feedback.warning(`Provider ${provider} 并发到上限，请稍后`, {
        description: payload.message ?? detail,
      });
    });

    es.addEventListener("error", () => {
      // 浏览器原生 EventSource 在 CONNECTING / OPEN 时自带重连（带 Last-Event-ID）；
      // 只在 CLOSED 时显式 close 让 GC 干净（fallback polling 没必要 —— 全局监听器
      // 不能阻塞业务页，断流静默就行）。
      if (es.readyState === EventSource.CLOSED) {
        es.close();
      }
    });

    return () => {
      es.close();
    };
  }, []);
}

function computeRemaining(
  snapshot: SnapshotPayload | null,
  payload: QuotaExceededPayload
): number | null {
  // 优先用 payload 自带数据（更新鲜，对应失败那一刻的 DB 状态）
  if (
    payload.monthly_limit != null &&
    payload.current_usage != null
  ) {
    return Math.max(0, payload.monthly_limit - payload.current_usage);
  }
  if (snapshot?.remaining_usd != null) return snapshot.remaining_usd;
  return null;
}
