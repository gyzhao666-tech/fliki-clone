import { api } from "@/lib/api";

export type PipelineStepState =
  | "pending"
  | "ready"
  | "running"
  | "awaiting_review"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export type PipelineRunState =
  | "queued"
  | "running"
  | "awaiting_review"
  | "partial_failed"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface PipelineStep {
  id: string;
  name: string;
  agent_type: string;
  state: PipelineStepState;
  attempt: number;
  requires_review: boolean;
  inputs_json: Record<string, unknown> | null;
  outputs_json: Record<string, unknown> | null;
  error: string | null;
  cost_usd: number;
}

export interface PipelineRun {
  id: string;
  file_id: string | null;
  user_id: string | null;
  template_name: string | null;
  state: PipelineRunState;
  cost_estimated_usd: number;
  cost_actual_usd: number;
  cost_reserved_usd: number;
  error: string | null;
  steps: PipelineStep[];
}

/**
 * 配额 v2：tenant 视图为权威源。
 * 旧字段（monthly_limit_usd / current_period_usage_usd / ...）继续映射到 tenant 数据，
 * 让历史 UI 不拆；新字段（tenant_id / tenant_plan / provider_buckets）渐进显示。
 */
export interface ProviderBucket {
  provider_name: string;
  current_in_flight: number;
  max_concurrent: number;
  remaining: number;
  utilization_pct: number;
}

export interface PipelineQuota {
  monthly_limit_usd: number;
  current_period_usage_usd: number;
  remaining_usd: number;
  current_period_start: string;
  concurrent_max: number;
  active_runs: number;
  // 配额 v2 新增
  tenant_id: string;
  tenant_plan: string;
  tenant_display_name: string | null;
  provider_buckets: ProviderBucket[];
}

export interface PipelineEstimate {
  total_usd: number;
  by_step: Array<{
    name: string;
    agent_type: string;
    est_usd: number;
    missing?: boolean;
  }>;
  missing_agents: string[];
}

export interface StartPipelinePayload {
  template_name: string;
  file_id?: string;
  brief?: Record<string, unknown>;
  target_topic?: unknown;
  custom_graph?: Array<{
    name: string;
    agent_type: string;
    depends_on?: string[];
    requires_review?: boolean;
  }>;
}

export function startPipeline(payload: StartPipelinePayload) {
  return api<PipelineRun>("/pipelines", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getPipeline(runId: string) {
  return api<PipelineRun>(`/pipelines/${runId}`);
}

export function tickPipeline(runId: string) {
  return api<PipelineRun>(`/pipelines/${runId}/tick`, { method: "POST" });
}

export function rerunPipelineStep(runId: string, name: string) {
  return api<PipelineStep>(
    `/pipelines/${runId}/steps/${encodeURIComponent(name)}/rerun`,
    { method: "POST" }
  );
}

export function approvePipelineStep(runId: string, name: string) {
  return api<PipelineRun>(
    `/pipelines/${runId}/steps/${encodeURIComponent(name)}/approve`,
    { method: "POST" }
  );
}

export function cancelPipeline(runId: string) {
  return api<PipelineRun>(`/pipelines/${runId}/cancel`, { method: "POST" });
}

export function getPipelineQuota() {
  return api<PipelineQuota>("/pipelines/quota");
}

export function getPipelineBuckets() {
  return api<ProviderBucket[]>("/pipelines/buckets");
}

export function estimatePipeline(payload: StartPipelinePayload) {
  return api<PipelineEstimate>("/pipelines/estimate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

const TERMINAL_RUN_STATES: PipelineRunState[] = ["succeeded", "failed", "cancelled"];

export function isRunTerminal(state: PipelineRunState) {
  return TERMINAL_RUN_STATES.includes(state);
}

const STEP_STATE_TONE: Record<PipelineStepState, string> = {
  pending: "muted",
  ready: "muted",
  running: "info",
  awaiting_review: "warning",
  succeeded: "success",
  failed: "danger",
  skipped: "muted",
  cancelled: "muted",
};

export function stepStateTone(state: PipelineStepState) {
  return STEP_STATE_TONE[state] ?? "muted";
}
