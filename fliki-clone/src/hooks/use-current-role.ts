/**
 * Track-27 · 当前用户角色探测 hook。
 *
 * 用法
 * ----
 * ```tsx
 * const role = useCurrentRole();
 * <Button disabled={!canWrite(role, role.loading)} title={disabledReason(role, role.loading)}>
 *   另存为版本
 * </Button>
 * ```
 *
 * 设计取舍
 * --------
 * - 单次 GET `/admin/feature-flags/me` 探测；不挂 SSE / 轮询，role 切换由
 *   T-30 workspace selector 触发 refetch 一次足够（v1 不做实时联动）
 * - 失败兜底视为「无权限」（ANON_ROLE）：让 viewer / 未登录都看不到写按钮，
 *   而不是让按钮亮着然后真点了报 403
 * - `loading=true` 时 `canWrite` / `canManageBilling` 返 false，避免 hook 还
 *   没回来 viewer 用户先点出 403（与 sidebar admin 入口探测同 pattern）
 * - 不缓存到 Redux / Zustand：`AdminMeOut` 后端已经按 `team_members` 60s 缓存，
 *   再加一层前端缓存收益微弱、复杂度上升
 */
"use client";

import { useEffect, useState } from "react";

import { getAdminMe } from "@/lib/admin-flags";
import { ANON_ROLE, type RoleSummary, summarizeRole } from "@/lib/role";

export interface CurrentRoleState extends RoleSummary {
  /** 探测是否还在 in-flight；true 期间所有 can* 判定都返 false 兜底 */
  loading: boolean;
  /** 探测错误信息（debug 用；UI 通常只看 loading + role） */
  error: string | null;
}

const ANON_STATE: CurrentRoleState = {
  ...ANON_ROLE,
  loading: true,
  error: null,
};

export function useCurrentRole(): CurrentRoleState {
  const [state, setState] = useState<CurrentRoleState>(ANON_STATE);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const me = await getAdminMe();
        if (cancelled) return;
        setState({
          ...summarizeRole(me),
          loading: false,
          error: null,
        });
      } catch (err) {
        if (cancelled) return;
        setState({
          ...ANON_ROLE,
          loading: false,
          error: err instanceof Error ? err.message : "role 探测失败",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
