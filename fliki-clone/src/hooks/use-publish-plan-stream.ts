"use client";

import { useEffect, useRef, useState } from "react";

import { listFilePublishPlans, PublishPlanOut } from "@/lib/production";

/**
 * usePublishPlanStream
 * ────────────────────
 * Track-03：把 publish 任务异步化后，前端 PlanRow 不再卡 30-60s HTTP；
 * 改用 EventSource 订阅 `/api/production/publish-plans/{id}/events` 拉
 * `publish_plan_state` 事件，实时把 Upload 按钮从 loading 转到终态。
 *
 * Track-13 扩展：YouTube adapter 改成 8 MiB chunked PUT 后，每片完会推
 * `upload_progress` 事件（含 percent / bytes_uploaded / total / chunk_index）
 * 让 PlanRow 渲一根进度条；`upload_progress` 不是终态事件（终态仍走
 * `publish_plan_state.phase=completed/system_error`）。
 *
 * 协议（与后端 `app/routers/production.py` + `services/publishing/executor.py` 对齐）：
 *   - event: snapshot              data: <PublishPlanOut>           连接首条；用它对齐全量
 *   - event: publish_plan_state    data: <PublishPlanStateEvent>    单事件
 *       phase ∈ "running" | "completed" | "system_error"
 *       completed 时 ok / status / external_id 已写回 plan，前端再拉一次列表拿权威值
 *   - event: upload_progress       data: <UploadProgressEvent>      Track-13：分片进度
 *       phase ∈ "downloading" | "uploading"
 *       uploading 阶段每完成一片推一次；percent 0-100；非终态
 *   - 注释行 `: ping`                                                心跳；EventSource 自动忽略
 *
 * 行为：
 *   - 启动 = `start(planId, fileId?)`：开 EventSource；fileId 用于 fallback polling
 *   - 终态 phase（completed / system_error）→ 自动关闭；onTerminal 回调
 *   - 连续 2 次 onerror → 退到 2.5s polling fallback（拉 /files/{fileId}/publish-plans
 *     比较本 plan.status；status 进入 published/failed/cancelled 视为终态）
 *   - 不传 fileId 时 polling 退化为 noop（终态判断只能靠 SSE 事件）
 *   - planId 变化 / unmount → 自动 cleanup
 *
 * 同源 + cookie 鉴权：fetch 现有 api.ts 已经用 `credentials: "include"`，
 * EventSource 用 `withCredentials: true` 同样带上 httpOnly token cookie。
 */

const POLL_INTERVAL_MS = 2500;
const FALLBACK_AFTER_FAILURES = 2;
const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  "published",
  "failed",
  "cancelled",
]);
const TERMINAL_PHASES: ReadonlySet<string> = new Set([
  "completed",
  "system_error",
]);

export type PublishPlanStreamMode = "idle" | "stream" | "polling";

export interface PublishPlanStateEvent {
  plan_id: string;
  phase: "running" | "completed" | "system_error";
  ok?: boolean;
  status?: string;
  external_id?: string | null;
  external_url?: string | null;
  error?: string | null;
}

/**
 * Track-13：分片上传进度事件 payload。
 * 由 youtube adapter 每完成一片调用 executor 注入的 progress_cb 后，
 * 通过 SSE 频道 `publish:plan:{id}` 推送过来。
 *
 * - `phase=downloading`：adapter 正在把 render_url 下载到内存；只发 1-2 次（开始/完成）
 * - `phase=uploading`：每个 chunk_size（默认 8 MiB）一次；percent 单调递增到 100
 */
export interface UploadProgressEvent {
  plan_id: string;
  phase: "downloading" | "uploading";
  bytes_uploaded: number;
  total: number;
  percent: number;
  chunk_index: number;
  chunk_count: number;
}

export interface PublishPlanStreamHandle {
  /** 当前 hook 的状态：未连 / SSE / polling */
  mode: PublishPlanStreamMode;
  /** true = 正在等 worker 跑（loading 转圈用） */
  pending: boolean;
  /** 最近一次 publish_plan_state 事件；null = 还没收到（snapshot 不算） */
  latestEvent: PublishPlanStateEvent | null;
  /** 最近一次 snapshot（异步路径返 202 时也只有这个 plan 视图最新） */
  latestPlan: PublishPlanOut | null;
  /** Track-13：最近一次 upload_progress 事件；null = 还没开始分片上传 */
  latestProgress: UploadProgressEvent | null;
  /** 启动订阅；planId 必填，fileId 用于 polling fallback */
  start: (planId: string, fileId?: string | null) => void;
  /** 主动停（不用等终态） */
  stop: () => void;
}

export interface UsePublishPlanStreamArgs {
  /** 终态 phase（completed / system_error）后回调一次；典型用法是刷新列表 */
  onTerminal?: (event: PublishPlanStateEvent | null) => void;
  /** snapshot 回调（连上时 + 终态后端再发也会触发），便于把 plan 同步到外部 state */
  onSnapshot?: (plan: PublishPlanOut) => void;
  /** 收到任何 publish_plan_state 事件时回调（含 running） */
  onEvent?: (event: PublishPlanStateEvent) => void;
  /** Track-13：收到 upload_progress 事件时回调（典型用法：自定义打点 / 分析） */
  onUploadProgress?: (event: UploadProgressEvent) => void;
}

export function usePublishPlanStream(
  args: UsePublishPlanStreamArgs = {}
): PublishPlanStreamHandle {
  const [mode, setMode] = useState<PublishPlanStreamMode>("idle");
  const [pending, setPending] = useState(false);
  const [latestEvent, setLatestEvent] =
    useState<PublishPlanStateEvent | null>(null);
  const [latestPlan, setLatestPlan] = useState<PublishPlanOut | null>(null);
  // Track-13：upload_progress 单事件态；下次 start() 重置回 null
  const [latestProgress, setLatestProgress] =
    useState<UploadProgressEvent | null>(null);

  // 回调挂 ref 避免每次 render 重建 EventSource
  const onTerminalRef = useRef(args.onTerminal);
  const onSnapshotRef = useRef(args.onSnapshot);
  const onEventRef = useRef(args.onEvent);
  const onUploadProgressRef = useRef(args.onUploadProgress);
  onTerminalRef.current = args.onTerminal;
  onSnapshotRef.current = args.onSnapshot;
  onEventRef.current = args.onEvent;
  onUploadProgressRef.current = args.onUploadProgress;

  // 当前活跃订阅的句柄（外部 start/stop 共享）
  const sessionRef = useRef<{
    planId: string | null;
    fileId: string | null;
    es: EventSource | null;
    pollHandle: ReturnType<typeof setTimeout> | null;
    closed: boolean;
    consecutiveErrors: number;
  }>({
    planId: null,
    fileId: null,
    es: null,
    pollHandle: null,
    closed: true,
    consecutiveErrors: 0,
  });

  const stop = () => {
    const session = sessionRef.current;
    session.closed = true;
    if (session.es) {
      session.es.close();
      session.es = null;
    }
    if (session.pollHandle) {
      clearTimeout(session.pollHandle);
      session.pollHandle = null;
    }
    setMode("idle");
    setPending(false);
  };

  const finishWith = (event: PublishPlanStateEvent | null) => {
    stop();
    onTerminalRef.current?.(event);
  };

  const startPolling = () => {
    const session = sessionRef.current;
    if (session.closed) return;
    if (!session.fileId || !session.planId) {
      // 没 fileId 没法拉列表；只能干等 SSE，不进 polling
      return;
    }
    setMode("polling");
    const tick = async () => {
      if (session.closed) return;
      try {
        const list = await listFilePublishPlans(session.fileId!);
        const found = list.find((p) => p.id === session.planId);
        if (found) {
          setLatestPlan(found);
          onSnapshotRef.current?.(found);
          if (TERMINAL_STATUSES.has(found.status)) {
            finishWith({
              plan_id: found.id,
              phase: found.status === "failed" ? "system_error" : "completed",
              ok: found.status === "published",
              status: found.status,
              external_id: found.external_id,
              error: found.error,
            });
            return;
          }
        }
      } catch {
        // 静默：下个 tick 再试
      }
      if (!session.closed) {
        session.pollHandle = setTimeout(tick, POLL_INTERVAL_MS);
      }
    };
    session.pollHandle = setTimeout(tick, POLL_INTERVAL_MS);
  };

  const start = (planId: string, fileId?: string | null) => {
    // 启动新 session 之前先 stop 旧的
    stop();
    const session = sessionRef.current;
    session.planId = planId;
    session.fileId = fileId ?? null;
    session.closed = false;
    session.consecutiveErrors = 0;
    setLatestEvent(null);
    setLatestProgress(null);
    setPending(true);

    const base =
      process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ??
      "http://localhost:8000";
    const url = `${base}/api/production/publish-plans/${encodeURIComponent(
      planId
    )}/events`;
    const es = new EventSource(url, { withCredentials: true });
    session.es = es;
    setMode("stream");

    es.addEventListener("snapshot", (ev) => {
      session.consecutiveErrors = 0;
      try {
        const plan = JSON.parse(
          (ev as MessageEvent).data
        ) as PublishPlanOut;
        setLatestPlan(plan);
        onSnapshotRef.current?.(plan);
        // 已是终态：服务端会立刻关闭 SSE；前端也提前结束 loading
        if (TERMINAL_STATUSES.has(plan.status)) {
          finishWith({
            plan_id: plan.id,
            phase: plan.status === "failed" ? "system_error" : "completed",
            ok: plan.status === "published",
            status: plan.status,
            external_id: plan.external_id,
            error: plan.error,
          });
        }
      } catch {
        /* ignore malformed */
      }
    });

    es.addEventListener("publish_plan_state", (ev) => {
      session.consecutiveErrors = 0;
      try {
        const payload = JSON.parse(
          (ev as MessageEvent).data
        ) as PublishPlanStateEvent;
        setLatestEvent(payload);
        onEventRef.current?.(payload);
        if (TERMINAL_PHASES.has(payload.phase)) {
          finishWith(payload);
        }
      } catch {
        /* ignore */
      }
    });

    // Track-13：分片上传进度事件（非终态；用于驱动 PlanRow 进度条）
    es.addEventListener("upload_progress", (ev) => {
      session.consecutiveErrors = 0;
      try {
        const payload = JSON.parse(
          (ev as MessageEvent).data
        ) as UploadProgressEvent;
        setLatestProgress(payload);
        onUploadProgressRef.current?.(payload);
      } catch {
        /* ignore malformed */
      }
    });

    es.addEventListener("error", () => {
      // SSE 重连机制不可靠（鉴权过期 / 后端重启 / redis 抖动）；自己计数 fallback
      session.consecutiveErrors += 1;
      if (session.consecutiveErrors >= FALLBACK_AFTER_FAILURES) {
        if (session.es) {
          session.es.close();
          session.es = null;
        }
        if (!session.closed) startPolling();
      }
    });
  };

  // unmount 自动清理
  useEffect(() => {
    return () => {
      stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    mode,
    pending,
    latestEvent,
    latestPlan,
    latestProgress,
    start,
    stop,
  };
}
