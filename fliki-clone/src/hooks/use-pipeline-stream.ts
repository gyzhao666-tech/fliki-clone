"use client";

import { useEffect, useRef, useState } from "react";

import {
  PipelineRun,
  PipelineRunState,
  PipelineStep,
  getPipeline,
  isRunTerminal,
} from "@/lib/pipelines";

/**
 * usePipelineStream
 * ─────────────────
 * 用浏览器原生 EventSource 订阅 `/api/pipelines/{run_id}/events`，
 * 把 backend 事件 patch 到调用方维护的 `run` state。
 *
 * 协议（与后端 `app/routers/pipelines.py` 对齐）：
 *   - event: snapshot   data: <PipelineRun>     连接首条；用它对齐全量
 *   - event: step_state data: <PipelineStep + run_id>  单步变化
 *   - event: run_state  data: <PipelineRun minus steps> run 顶层变化
 *   - 注释行 `: ping`                              心跳；EventSource 自动忽略
 *
 * 行为：
 *   - 连接错误且未达终态 → 退到 2.5s polling fallback（保留旧行为，避免全黑屏）
 *   - run 终态 → 关闭 EventSource + polling
 *   - 输入 runId 变化时自动重连
 *
 * 同源 + cookie 鉴权：fetch 现有 api.ts 已经用 `credentials: "include"`，
 * EventSource 用 `withCredentials: true` 同样带上 httpOnly token cookie。
 */

const POLL_INTERVAL_MS = 2500;
const FALLBACK_AFTER_FAILURES = 2; // 连续失败次数 → 退到 polling

type StreamMode = "idle" | "stream" | "polling";

export interface UsePipelineStreamArgs {
  runId: string | null;
  enabled?: boolean;
  /** 拿到任何状态变化时的更新函数；用 functional updater 避免闭包陷阱 */
  onUpdate: (
    updater: (prev: PipelineRun | null) => PipelineRun | null
  ) => void;
  /** 进入终态时调用一次，便于刷新 quota / 弹 toast */
  onTerminal?: (run: PipelineRun | null) => void;
}

export function usePipelineStream({
  runId,
  enabled = true,
  onUpdate,
  onTerminal,
}: UsePipelineStreamArgs) {
  const [mode, setMode] = useState<StreamMode>("idle");

  // 把回调挂 ref，避免每次 render 重建 EventSource
  const onUpdateRef = useRef(onUpdate);
  const onTerminalRef = useRef(onTerminal);
  onUpdateRef.current = onUpdate;
  onTerminalRef.current = onTerminal;

  useEffect(() => {
    if (!runId || !enabled) {
      setMode("idle");
      return;
    }

    let closed = false;
    let es: EventSource | null = null;
    let pollHandle: ReturnType<typeof setTimeout> | null = null;
    let consecutiveErrors = 0;
    let latestRun: PipelineRun | null = null;

    const cleanup = () => {
      closed = true;
      if (es) {
        es.close();
        es = null;
      }
      if (pollHandle) {
        clearTimeout(pollHandle);
        pollHandle = null;
      }
    };

    const finishIfTerminal = (state: PipelineRunState | undefined) => {
      if (state && isRunTerminal(state)) {
        cleanup();
        onTerminalRef.current?.(latestRun);
        setMode("idle");
        return true;
      }
      return false;
    };

    const startPolling = () => {
      if (closed) return;
      setMode("polling");
      const tick = async () => {
        if (closed) return;
        try {
          const next = await getPipeline(runId);
          latestRun = next;
          onUpdateRef.current(() => next);
          if (finishIfTerminal(next.state)) return;
        } catch {
          // 静默：下个 tick 再试
        }
        if (!closed) pollHandle = setTimeout(tick, POLL_INTERVAL_MS);
      };
      pollHandle = setTimeout(tick, POLL_INTERVAL_MS);
    };

    const startStream = () => {
      const base =
        process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ??
        "http://localhost:8000";
      const url = `${base}/api/pipelines/${encodeURIComponent(runId)}/events`;
      es = new EventSource(url, { withCredentials: true });
      setMode("stream");

      es.addEventListener("snapshot", (ev) => {
        consecutiveErrors = 0;
        try {
          const run = JSON.parse((ev as MessageEvent).data) as PipelineRun;
          latestRun = run;
          onUpdateRef.current(() => run);
          finishIfTerminal(run.state);
        } catch {
          /* ignore malformed */
        }
      });

      es.addEventListener("step_state", (ev) => {
        consecutiveErrors = 0;
        try {
          const payload = JSON.parse(
            (ev as MessageEvent).data
          ) as PipelineStep & { run_id?: string };
          const incoming: PipelineStep = {
            id: payload.id,
            name: payload.name,
            agent_type: payload.agent_type,
            state: payload.state,
            attempt: payload.attempt,
            requires_review: payload.requires_review,
            inputs_json: payload.inputs_json ?? null,
            outputs_json: payload.outputs_json ?? null,
            error: payload.error ?? null,
            cost_usd: payload.cost_usd ?? 0,
          };
          onUpdateRef.current((prev) => {
            if (!prev) return prev;
            const idx = prev.steps.findIndex((s) => s.id === incoming.id);
            const nextSteps =
              idx >= 0
                ? prev.steps.map((s, i) => (i === idx ? incoming : s))
                : [...prev.steps, incoming];
            const next = { ...prev, steps: nextSteps };
            latestRun = next;
            return next;
          });
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("run_state", (ev) => {
        consecutiveErrors = 0;
        try {
          const payload = JSON.parse((ev as MessageEvent).data) as Omit<
            PipelineRun,
            "steps"
          > & { steps?: never };
          let nextRun: PipelineRun | null = null;
          onUpdateRef.current((prev) => {
            if (!prev) return prev;
            nextRun = { ...prev, ...payload, steps: prev.steps };
            latestRun = nextRun;
            return nextRun;
          });
          finishIfTerminal(payload.state);
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("error", () => {
        // SSE 自动重连机制不可靠（鉴权过期 / 后端重启），自己计数 fallback
        consecutiveErrors += 1;
        if (consecutiveErrors >= FALLBACK_AFTER_FAILURES) {
          if (es) {
            es.close();
            es = null;
          }
          if (!closed) startPolling();
        }
      });
    };

    startStream();
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, enabled]);

  return { mode };
}
