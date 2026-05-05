# Track-30 · workspace 切换 UI + 后端 list-my-workspaces 路由

> 分支：`track-30-workspace-switcher`（基于 `292f4ff`）
> 范围：第七波 L-15 — sidebar 顶部 workspace selector + 后端列表路由

## 改了什么

### 后端（1 modified + 1 new）

- **`fliki-clone-api/app/routers/team.py`**（在末尾追加，**不动**既有 4 端点）
  - 加 inline pydantic schema：`WorkspaceMembershipOut` (`id, name, role, is_owner, created_at`) + `WorkspacesListOut`
  - 加 route `GET /team/workspaces/me`（mount 后即 `/api/team/workspaces/me`）
  - 实现：
    1. `team_members JOIN workspaces` 拉所有 `team_members.user_id == current_user.id` 的 workspace + role
    2. UNION 自己 own 的（不在 team_members 里的）workspace，role 兜底 `admin`
    3. 排序 `created_at ASC`（让前端 sidebar 默认选最早 own 的）
  - **去重语义**：owner 同时在 team_members 里时，team_members.role 优先（与 PATCH 降级语义一致；T-24 backfill 后 owner 默认就是 admin）
- **`fliki-clone-api/tests/test_track30_workspaces.py`**（新文件，6 case）
  - `test_owner_only_no_team_members_returns_admin` — owner-only fallback 路径
  - `test_owner_plus_membership_in_other_workspace_returns_two` — own + member 共 2 条
  - `test_role_comes_from_team_members_when_owner_also_member` — owner 同时是 viewer → role=viewer 优先
  - `test_empty_user_returns_zero_workspaces` — 空用户返 200 + `[]`
  - `test_unauthenticated_returns_401` — 既有 `get_current_user` 依赖抛 401
  - `test_invited_pending_member_with_user_id_appears_in_list` — pending status 也可见

### 前端（3 new + 2 modified）

- **`fliki-clone/src/lib/workspaces.ts`**（新）
  - 类型 `WorkspaceMembership { id, name, role, is_owner, created_at }`、`WorkspacesListOut`、`WorkspaceRole`
  - `listMyWorkspaces()` 调 `GET /team/workspaces/me`
- **`fliki-clone/src/hooks/use-current-workspace.ts`**（新）
  - `<WorkspaceProvider>` Context Provider（用 `createElement` 避免 .tsx 文件名）
  - `useCurrentWorkspace(): { current, list, switchTo, loading, error, refresh }`
  - localStorage key `fliki:current-workspace-id` 持久化；首次加载时若存的 id 还在 list 里就用它，否则用 `list[0]`
  - `switchTo(id)` 写 localStorage + setState（不强制 page-level refetch；follow-up 处理）
- **`fliki-clone/src/components/app-shell/workspace-selector.tsx`**（新）
  - shadcn `<DropdownMenu>` 实现（项目里没有 `<Select>`）
  - 列每个 workspace 名 + role badge（admin 紫 / editor sky / viewer slate，与 spec 一致）
  - loading 占位 + 空 list 防御文案 + 当前选中 ✓ 角标
- **`fliki-clone/src/app/[locale]/(app)/layout.tsx`**（修改）
  - 在最外层 wrap `<WorkspaceProvider>`；T-25 加的 `<UserEventsListener />` 不动（保留在 AppShell 内）
- **`fliki-clone/src/components/app-shell/sidebar.tsx`**（修改）
  - 在 logo 段（行 100-106）下方插入 `<WorkspaceSelector />`，独立 `<div>` 带 border-b 分隔
  - **严格不动**：admin links 段（行 127-145）/ primaryNav / libraryNav / Upgrade plan footer / 任何其它段
  - 加 1 行 import：`@/components/app-shell/workspace-selector`

### 文档（1 new）

- **`TRACK_30_NOTES.md`**（本文件）

## 烟测命令 + 结果

### 后端

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && make test
```

结果：**146 passed in 2.82s**（130 baseline + 6 我的 + 10 其它合并到 main 但本批没碰；fluctuation 与并行 wave 里 T-27 落库 case 有关，本 Track 不依赖）

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m pytest tests/test_track30_workspaces.py -v
```

结果：**6 passed**（6/6 my new cases）

### 前端

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone && npx tsc --noEmit
```

结果：**0 errors**（pre-existing pipeline/page.tsx 引用 use-audio-current-word 在并行 T-26 working tree 下已自然修复；本 Track 不引入新 TS 错）

## 已知边界（本 Track 故意不做）

- **`_get_or_create_workspace` 未动**：team.py 既有 4 端点（list/invite/patch/delete members）仍按 owner 兜底（取 user 的 own workspace），sidebar 切到 member 身份的另 workspace 后，调用这些端点仍只看到 own workspace 的成员。**多租户隔离 API guard 留给下次 Track**，需要：
  - `current_workspace_id` 透传机制（cookie / header / query）
  - 现有路由从「只看 own」升级为「看 current_workspace」
  - `_require_workspace_access(user_id, ws_id)` 守门
- **workspace 切换后 page-level queries 不强制 refetch**：本 Track 只更新 `current` 状态 + localStorage；各 page（pipeline / billing / files）的 react-query 仍用旧 cache。临时方案：用户手动刷新页面；正式方案见下方 follow-up。
- **没改 `routers/admin_flags.py /me` 端点 schema**：T-27 在并行做 admin_flags `is_admin`/`is_editor`/`is_viewer` 扩展；本 Track 不碰，避免互相踩。

## Follow-up

1. **emit 自定义事件让各 page 监听 invalidate**（**优先级 P1**）
   - 在 `useCurrentWorkspace.switchTo` 内 `window.dispatchEvent(new CustomEvent("fliki:workspace-changed", { detail: { id } }))`
   - 各 page hook（`use-files`, `use-publish-plans`, etc.）`useEffect` 监听该事件 → 调 react-query 的 `queryClient.invalidateQueries(...)`
2. **多租户 API guard**：把 `current_workspace_id` 写到 cookie（http-only），后端 `Depends(get_current_workspace)` 自动注入；现有「按 user.id 拿 own」逻辑批量升级为「按 user.id + workspace_id」
3. **workspace 创建 / 删除 UI**：当前只能在 settings/team 看，dropdown 里加 "+ Create workspace" / "Manage" 入口
4. **sidebar 在 SSR 阶段**：当前 `WorkspaceProvider` 在 mount 才拉 list，初次渲染时 selector 渲 "Loading…"。可优化：layout.tsx server-side 预拉一次 → cookies/headers 同步；本 Track 不做（v1 体验可接受）

## 互斥锁严格遵守

- 后端：仅 `routers/team.py` 末尾新增 1 路由 + inline schema（**不动** invite / list / patch / delete members 4 端点）+ 新 test 文件
- 前端：全部新文件（`lib/workspaces.ts` / `hooks/use-current-workspace.ts` / `components/app-shell/workspace-selector.tsx`）+ `(app)/layout.tsx` 最外层 1 个 Provider wrap（T-25 的 `<UserEventsListener />` 完整保留）+ `sidebar.tsx` logo 段下方 1 行 `<WorkspaceSelector />`（**绝对不动** admin links 段，让 T-27 安全）
- **不动**（按 spec）：`rbac.py` / `admin-flags.ts` / VoiceArtifact / docker-compose / docs/adr
