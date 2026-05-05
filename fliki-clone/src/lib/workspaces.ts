/**
 * Workspaces 客户端（Track-30）。
 *
 * 与后端 `app/routers/team.py::list_my_workspaces` 一一对应：
 * - `GET /api/team/workspaces/me` 列当前 user 所有可见 workspace（own + 受邀）
 *
 * 设计取舍
 * --------
 * - 类型与后端 `WorkspaceMembershipOut` pydantic schema 字段名严格对齐
 *   （id / name / role / is_owner / created_at），避免 ad-hoc 改名
 * - role 收窄为 union 字面量：sidebar / use-current-workspace 用 narrowing 决定
 *   badge 样式 / 权限判定，不引入运行时校验（后端已 backfill + default='editor'）
 * - 不在本文件做 React 状态管理；Provider / hook 在 `hooks/use-current-workspace.ts`
 *   独立实现，本文件仅返 raw API
 */
import { api } from "@/lib/api";

export type WorkspaceRole = "admin" | "editor" | "viewer";

export interface WorkspaceMembership {
  id: string;
  name: string;
  role: WorkspaceRole;
  is_owner: boolean;
  created_at: string;
}

export interface WorkspacesListOut {
  workspaces: WorkspaceMembership[];
}

/** 拉当前用户所有可见 workspace + 各自 role。空数组表示用户没任何 workspace。 */
export function listMyWorkspaces() {
  return api<WorkspacesListOut>("/team/workspaces/me");
}
