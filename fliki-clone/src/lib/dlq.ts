/**
 * 死信队列客户端（与后端 `app/routers/dlq.py` 一一对应）。
 *
 * 设计：
 * - 强类型 + 薄 fetch 包装，沿用 `production.ts` 的 `api()` 模式
 * - 状态字面量与后端 `dead_letter_tasks.status` 三态对齐
 * - 列表端点支持 status / run_id 过滤；UI 侧默认筛 `pending`
 */
import { api } from "@/lib/api";

export type DlqStatus = "pending" | "retried" | "discarded";

export const DLQ_STATUSES: DlqStatus[] = ["pending", "retried", "discarded"];

export interface DlqItemOut {
  id: string;
  task_name: string;
  args_json: unknown[] | null;
  kwargs_json: Record<string, unknown> | null;
  run_id: string | null;
  step_id: string | null;
  user_id: string | null;
  error: string;
  traceback: string | null;
  attempt_count: number;
  status: DlqStatus;
  notes: string | null;
  first_failed_at: string;
  last_failed_at: string;
  created_at: string;
  updated_at: string;
}

export interface DlqRetryResult {
  id: string;
  dispatcher: "celery" | "background";
  notes: string | null;
}

export interface ListDlqParams {
  status?: DlqStatus;
  runId?: string;
  limit?: number;
}

export function listDlq(params: ListDlqParams = {}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.runId) qs.set("run_id", params.runId);
  if (params.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return api<DlqItemOut[]>(`/dlq${suffix}`);
}

export function getDlq(id: string) {
  return api<DlqItemOut>(`/dlq/${id}`);
}

export function retryDlq(id: string) {
  return api<DlqRetryResult>(`/dlq/${id}/retry`, { method: "POST" });
}

export function discardDlq(id: string, notes?: string) {
  return api<DlqItemOut>(`/dlq/${id}/discard`, {
    method: "POST",
    body: JSON.stringify(notes ? { notes } : {}),
  });
}
