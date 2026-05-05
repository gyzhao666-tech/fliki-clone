/**
 * Admin · Feature Flags 客户端（Track-14）。
 *
 * 与后端 `app/routers/admin_flags.py` 一一对应：
 * - `GET    /admin/feature-flags/me`               非 admin 也能调，不抛 403（探测端点）
 * - `GET    /admin/feature-flags/tenants`          列出有 flag 的 tenant
 * - `GET    /admin/feature-flags?tenant_id=...`    某 tenant 全部 flag + known_flags 提示
 * - `GET    /admin/feature-flags/{tid}/{name}`     单 flag value
 * - `PUT    /admin/feature-flags/{tid}/{name}`     upsert
 * - `DELETE /admin/feature-flags/{tid}/{name}`     删除（幂等：404 不存在算 deleted=false）
 *
 * 设计取舍
 * --------
 * - 类型与后端 pydantic schema 字段名严格对齐，避免 union 类型在 page 上重命名
 * - value 形态保持 `Record<string, unknown>`，由 page 层按 `pct` / `enabled` /
 *   `variant` 分支渲染；新形态加进去不需要改本文件
 * - `getAdminMe` 设计为「非 admin 不抛 403」便于 Sidebar 一进来就探测
 *   （admin 入口本就是 server-side 鉴权兜底，前端隐藏只是降噪）
 */
import { api } from "@/lib/api";

export type FlagValue = Record<string, unknown>;

export interface AdminFlagOut {
  tenant_id: string;
  flag_name: string;
  value_json: FlagValue;
}

export interface FlagListOut {
  tenant_id: string;
  flags: Record<string, FlagValue>;
  known_flags: Record<string, string>;
}

export interface TenantSummary {
  tenant_id: string;
  flag_count: number;
}

export interface TenantsListOut {
  tenants: TenantSummary[];
  known_flags: Record<string, string>;
}

/**
 * `/admin/feature-flags/me` 探测端点响应。
 *
 * Track-27 起新加 `role` / `is_editor` / `is_viewer` 三字段，让前端按 role 灰化按钮。
 *
 * - `is_admin`：保留 Track-14 既有语义（含邮箱白名单 fallback）；sidebar 只看这一个
 * - `is_editor`：仅 team_members.role in (admin, editor) 命中（**不**走邮箱兜底）
 * - `is_viewer`：team_members 任意行命中（**不**走邮箱兜底）
 * - `role`：用户最高 role（admin > editor > viewer）；没在任何 workspace 登记 → null
 */
export interface AdminMeOut {
  is_admin: boolean;
  is_editor: boolean;
  is_viewer: boolean;
  role: "admin" | "editor" | "viewer" | null;
  email: string | null;
}

export interface DeleteFlagResult {
  tenant_id: string;
  flag_name: string;
  deleted: boolean;
}

/** 探测当前登录用户是否 admin；非 admin 也返 200，避免 sidebar 控制台一片红。 */
export function getAdminMe() {
  return api<AdminMeOut>("/admin/feature-flags/me");
}

/** 列出有 flag 落库的 tenant + 每个 tenant 的 flag 数量 + KNOWN_FLAGS 字典。 */
export function listTenants() {
  return api<TenantsListOut>("/admin/feature-flags/tenants");
}

/** 列某 tenant 全部 flag。 */
export function listTenantFlags(tenantId: string) {
  const qs = new URLSearchParams({ tenant_id: tenantId }).toString();
  return api<FlagListOut>(`/admin/feature-flags?${qs}`);
}

/** upsert 单 flag；返回写入后的 value_json（normalised）。 */
export function setTenantFlag(
  tenantId: string,
  flagName: string,
  value: FlagValue
) {
  return api<AdminFlagOut>(
    `/admin/feature-flags/${encodeURIComponent(tenantId)}/${encodeURIComponent(
      flagName
    )}`,
    {
      method: "PUT",
      body: JSON.stringify({ value }),
    }
  );
}

/** 删除单 flag；deleted=false 表示原本不存在（不报错）。 */
export function deleteTenantFlag(tenantId: string, flagName: string) {
  return api<DeleteFlagResult>(
    `/admin/feature-flags/${encodeURIComponent(tenantId)}/${encodeURIComponent(
      flagName
    )}`,
    { method: "DELETE" }
  );
}

// ── value 形态判定（page 表格按形态渲染编辑器）─────────────────────────────────

export type FlagShape = "pct" | "enabled" | "variant" | "raw";

/** 与后端 `feature_flags.is_enabled` 三种形态对齐；其它落 raw（前端只能 JSON 编辑）。 */
export function detectFlagShape(value: FlagValue | undefined | null): FlagShape {
  if (!value || typeof value !== "object") return "raw";
  if ("pct" in value) return "pct";
  if ("enabled" in value) return "enabled";
  if ("variant" in value) return "variant";
  return "raw";
}
