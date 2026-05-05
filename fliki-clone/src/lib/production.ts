/**
 * 生产元数据查询客户端（与后端 `app/routers/production.py` 一一对应）。
 *
 * 设计：
 * - 只暴露强类型 + 薄 fetch 包装；不维护本地缓存（用 React Query / SWR 时再加）
 * - 所有端点都基于 `api()`（自动带 cookie + JSON 处理）
 * - publish_plans / versions 提供 CRUD；shots / renders / reviews / metrics 是只读
 */
import { api } from "@/lib/api";

// ── shots & shot lists ──────────────────────────────────────────────────────

export interface ShotOut {
  id: string;
  index: number;
  duration_s: number;
  narration: string | null;
  visual: string | null;
  camera: string | null;
  enhanced_prompt: string | null;
  negative_prompt: string | null;
  aspect_ratio: string | null;
  focus_character: string | null;
  keyframe_url: string | null;
  keyframe_provider: string | null;
  keyframe_model: string | null;
  keyframe_size: string | null;
  keyframe_error: string | null;
  video_url: string | null;
  video_provider: string | null;
  video_model: string | null;
  video_mode: string | null;
  video_cost_usd: number;
  video_duration_ms: number;
  video_error: string | null;
}

export interface ShotListOut {
  id: string;
  run_id: string;
  file_id: string | null;
  title: string | null;
  hook: string | null;
  script: string | null;
  cta: string | null;
  aspect_ratio: string | null;
  topic: Record<string, unknown> | null;
  style_board: Record<string, unknown> | null;
  character_cards: Array<Record<string, unknown>> | null;
  shots: ShotOut[];
}

export function getRunShotList(runId: string) {
  return api<ShotListOut | null>(`/production/runs/${runId}/shot-list`);
}

// ── renders ─────────────────────────────────────────────────────────────────

export interface RenderOut {
  id: string;
  run_id: string;
  file_id: string | null;
  aspect_ratio: string;
  aspect_fit: string | null;
  is_primary: boolean;
  url: string | null;
  silent_video_url: string | null;
  subtitle_url: string | null;
  narration_url: string | null;
  duration_s: number;
  shot_count: number;
  file_size_bytes: number | null;
  muxed: boolean;
  burned_in_subtitles: boolean;
  looped_video: boolean;
  status: string;
  warning: string | null;
  created_at: string;
}

export function getRunRenders(runId: string) {
  return api<RenderOut[]>(`/production/runs/${runId}/renders`);
}

export function getFileRenders(fileId: string) {
  return api<RenderOut[]>(`/production/files/${fileId}/renders`);
}

// ── reviews ─────────────────────────────────────────────────────────────────

export interface ReviewOut {
  id: string;
  run_id: string;
  step_id: string | null;
  severity: "error" | "warning" | "info";
  area: string;
  message: string;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export function getRunReviews(runId: string) {
  return api<ReviewOut[]>(`/production/runs/${runId}/reviews`);
}

// ── metrics ─────────────────────────────────────────────────────────────────

export interface MetricOut {
  id: string;
  run_id: string | null;
  step_id: string | null;
  file_id: string | null;
  kind: string;
  value_num: number | null;
  value_text: string | null;
  unit: string | null;
  captured_at: string;
}

export function getRunMetrics(runId: string, kind?: string) {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return api<MetricOut[]>(`/production/runs/${runId}/metrics${qs}`);
}

// ── publish plans ───────────────────────────────────────────────────────────

export type PublishPlanStatus =
  | "draft"
  | "scheduled"
  | "published"
  | "failed"
  | "cancelled";

export const PUBLISH_PLAN_STATUSES: PublishPlanStatus[] = [
  "draft",
  "scheduled",
  "published",
  "failed",
  "cancelled",
];

export interface PublishPlanOut {
  id: string;
  file_id: string;
  run_id: string | null;
  render_id: string | null;
  platform: string;
  status: PublishPlanStatus;
  scheduled_at: string | null;
  published_at: string | null;
  external_id: string | null;
  title: string | null;
  description: string | null;
  tags: string[] | null;
  cover_url: string | null;
  error: string | null;
  /**
   * Track-02 真发安全闸门：默认 false = adapter 走 mock 路径；
   * true = youtube adapter 真打外部 API（dry-run / bilibili adapter 不读这字段）。
   */
  confirm_real_publish: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreatePublishPlanPayload {
  file_id: string;
  render_id?: string;
  run_id?: string;
  platform: string;
  title?: string;
  description?: string;
  tags?: string[];
  cover_url?: string;
  scheduled_at?: string; // ISO
}

export interface PatchPublishPlanPayload {
  status?: PublishPlanStatus;
  scheduled_at?: string | null;
  published_at?: string | null;
  external_id?: string;
  title?: string;
  description?: string;
  tags?: string[];
  cover_url?: string;
  render_id?: string;
  error?: string;
  /** Track-02 真发安全闸门 toggle */
  confirm_real_publish?: boolean;
}

export function listFilePublishPlans(fileId: string) {
  return api<PublishPlanOut[]>(`/production/files/${fileId}/publish-plans`);
}

export function createPublishPlan(payload: CreatePublishPlanPayload) {
  return api<PublishPlanOut>("/production/publish-plans", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function patchPublishPlan(id: string, payload: PatchPublishPlanPayload) {
  return api<PublishPlanOut>(`/production/publish-plans/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deletePublishPlan(id: string) {
  return api<{ deleted: boolean }>(`/production/publish-plans/${id}`, {
    method: "DELETE",
  });
}

// ── 发布执行器（v1）──────────────────────────────────────────────────────────

export interface PublishOutcomeOut {
  plan_id: string;
  ok: boolean;
  status: PublishPlanStatus | "failed";
  external_id: string | null;
  external_url: string | null;
  error: string | null;
  plan: PublishPlanOut | null;
}

export interface PlatformOut {
  name: string;
  is_real: boolean;
  requires_credential: boolean;
}

export interface CredentialOut {
  id: string;
  user_id: string;
  platform: string;
  display_name: string | null;
  external_user_id: string | null;
  has_access_token: boolean;
  has_refresh_token: boolean;
  token_expires_at: string | null;
  scope: string[];
  status: string;
}

export interface OAuthStartOut {
  authorize_url: string;
  state: string;
}

export function executePublishPlan(planId: string) {
  return api<PublishOutcomeOut>(
    `/production/publish-plans/${planId}/execute`,
    { method: "POST" }
  );
}

export function listPlatforms() {
  return api<PlatformOut[]>("/production/platforms");
}

export function listPlatformCredentials() {
  return api<CredentialOut[]>("/production/platforms/credentials");
}

export function startPlatformOAuth(platform: string) {
  return api<OAuthStartOut>(
    `/production/platforms/${platform}/oauth/start`,
    { method: "POST" }
  );
}

export function revokePlatformCredentials(platform: string) {
  return api<{ deleted: boolean }>(
    `/production/platforms/${platform}/credentials`,
    { method: "DELETE" }
  );
}

// ── versions ────────────────────────────────────────────────────────────────

export interface VersionOut {
  id: string;
  file_id: string;
  run_id: string;
  label: string;
  primary_render_id: string | null;
  is_published: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateVersionPayload {
  file_id: string;
  run_id: string;
  label: string;
  primary_render_id?: string;
  notes?: string;
  is_published?: boolean;
}

export function listFileVersions(fileId: string) {
  return api<VersionOut[]>(`/production/files/${fileId}/versions`);
}

export function createVersion(payload: CreateVersionPayload) {
  return api<VersionOut>("/production/versions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function publishVersion(id: string) {
  return api<VersionOut>(`/production/versions/${id}/publish`, {
    method: "POST",
  });
}

export function deleteVersion(id: string) {
  return api<{ deleted: boolean }>(`/production/versions/${id}`, {
    method: "DELETE",
  });
}
