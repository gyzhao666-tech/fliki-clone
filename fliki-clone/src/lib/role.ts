/**
 * Track-27 · 角色判定薄 helper。
 *
 * 与后端 `app/services/auth/rbac.py` 一一对应：
 *
 *   admin  ─ 计费 / 全平台管理（含邮箱白名单 fallback）
 *   editor ─ 创建 / 修改 / 删除内容（versions / publish_plans / pipeline 启停）
 *   viewer ─ 仅读
 *
 * 设计取舍
 * --------
 * - 与后端 `is_admin` / `is_editor` / `is_viewer` 字段对齐，前端不做语义推断
 *   （避免「前端以为自己是 editor 但后端返 403」的判定漂移）
 * - 路由 / 按钮鉴权前端只控展示，**真实鉴权仍以后端 require_role 为准**
 * - tooltip 文案集中在 `disabledReason()`，让 ProductionPanel / PlanRow / billing
 *   都共用同一份「需要 admin/editor 权限」中文提示
 */
import type { AdminMeOut } from "@/lib/admin-flags";

export type Role = "admin" | "editor" | "viewer";

export const ROLE_LABEL_ZH: Record<Role | "none", string> = {
  admin: "管理员",
  editor: "编辑者",
  viewer: "只读",
  none: "未登记",
};

export interface RoleSummary {
  /** 后端权威 role；可能为 null（dev / 邮箱白名单 fallback admin） */
  role: Role | null;
  isAdmin: boolean;
  isEditor: boolean;
  isViewer: boolean;
}

export const ANON_ROLE: RoleSummary = {
  role: null,
  isAdmin: false,
  isEditor: false,
  isViewer: false,
};

/** 把后端 AdminMeOut 摊平成 RoleSummary（默认值兜底，避免老后端没扩 schema 时 undefined）。*/
export function summarizeRole(me: AdminMeOut | null | undefined): RoleSummary {
  if (!me) return ANON_ROLE;
  return {
    role: (me.role ?? null) as Role | null,
    isAdmin: !!me.is_admin,
    // 老后端没回这俩字段时按 isAdmin 推断（admin 自然包含写权限）
    isEditor: !!me.is_editor || !!me.is_admin,
    isViewer: !!me.is_viewer || !!me.is_admin,
  };
}

/**
 * 写权限判定（按钮 disable 用）。
 *
 * 与后端 `require_role(["admin","editor"])` 对齐：admin 或 editor 都能写。
 * loading 阶段视为「不可写」，避免 viewer 用户在 hook 还没探测完时点出 403。
 */
export function canWrite(summary: RoleSummary, loading: boolean): boolean {
  if (loading) return false;
  return summary.isAdmin || summary.isEditor;
}

/**
 * admin-only 判定（计费按钮专用）。
 *
 * 与后端 `require_role(["admin"])` 对齐：仅 admin 能发起计费。
 */
export function canManageBilling(summary: RoleSummary, loading: boolean): boolean {
  if (loading) return false;
  return summary.isAdmin;
}

/**
 * 灰化按钮的 tooltip 文案；命中场景：
 *
 * - 写端点（versions / publish_plans / pipeline 启停）→ "需要 admin/editor 权限"
 * - 计费端点（checkout / portal）→ "需要 admin 权限"
 *
 * loading 阶段返 "正在确认权限…" 让用户知道是 hook 还没探完，而不是真没权限。
 * 命中通过时返 null（caller 判 null 决定是否挂 title）。
 */
export function disabledReason(
  summary: RoleSummary,
  loading: boolean,
  options: { adminOnly?: boolean } = {}
): string | null {
  if (loading) return "正在确认权限…";
  if (options.adminOnly) {
    return canManageBilling(summary, loading) ? null : "需要 admin 权限";
  }
  return canWrite(summary, loading) ? null : "需要 admin/editor 权限";
}
