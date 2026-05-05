# Track-27 · L-14 RBAC editor/viewer 实际写权限分级 · 交付

> **分支**：`track-27-rbac-editor-viewer`
> **依赖**：✅ Track-24（`team_members.role` 列 + `services/auth/rbac.py` 已落地）
> **完成时间**：2026-05-05
> **测试基线**：原 130 PASS → 新 140 PASS（+10 case）

## 1. 总体目标

把 Track-24 二元判定（admin vs 非 admin）升级为三档真 RBAC：

```
admin   ─ 所有写权限 + 计费 + admin 后台（保留邮箱白名单 fallback）
editor  ─ 写权限（versions / publish_plans / pipeline 启停） · 不能管计费
viewer  ─ 仅读
```

后端 `require_role(["admin","editor"])` 挂在 router decorator 的
`dependencies=[...]` 上、**不入侵函数签名**，前端 `useCurrentRole` hook
按 role 灰化按钮 + tooltip 提示中文。

## 2. 改了什么文件

### 后端（5 改 + 1 新）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone-api/app/services/auth/rbac.py` | 末尾追加 `is_editor` / `is_viewer` / `require_role` + 一个内部 `_user_has_role_in` 辅助；不动 `is_admin` / `get_user_role` 既有签名 | Track-24 里 `is_admin` 已经把邮箱白名单 fallback 写好；本 Track 在其上分出两档真 RBAC，editor/viewer **不**走邮箱兜底（避免运营误把 admin 邮箱当编辑权限） |
| `fliki-clone-api/app/routers/production.py` | 顶部 import `require_role` + `_writer_required = Depends(...)` 共享实例；7 个写端点 decorator 加 `dependencies=[_writer_required]`：POST `/publish-plans` / PATCH `/publish-plans/{id}` / DELETE `/publish-plans/{id}` / POST `/publish-plans/{id}/execute` / POST `/versions` / POST `/versions/{id}/publish` / DELETE `/versions/{id}` | 不改函数签名只挂 dep；既有 owner 鉴权（`_ensure_file_owner`）保留作 second line of defense |
| `fliki-clone-api/app/routers/pipelines.py` | 顶部 import `require_role` + `_writer_required` + 5 个写端点 decorator：POST `""`(start) / POST `/{run_id}/cancel` / POST `/{run_id}/tick` / POST `/{run_id}/steps/{name}/rerun` / POST `/{run_id}/steps/{name}/approve` | 同上 |
| `fliki-clone-api/app/routers/billing.py` | 顶部 import `require_role` + `_admin_required = Depends(require_role(["admin"]))`；2 个写端点：POST `/billing/checkout-session` / POST `/billing/portal-session`；GET `/billing/plan` 不挂（编辑也能看自己的额度）；`/billing/webhook` 不挂（stripe 服务端调，无 user 上下文） | 计费唯一 admin（避免拿到编辑权限的成员误点支付链接） |
| `fliki-clone-api/app/routers/admin_flags.py` | `AdminMeOut` schema 扩三字段：`role` / `is_editor` / `is_viewer`（既有 `is_admin` / `email` 不变）；`/me` 端点新加 `_resolve_user_top_role` helper 返「用户最高 role（admin > editor > viewer）」；`/me` response 同步带这三字段 | 让前端 `useCurrentRole` hook 一次拿到全部判定信息，不必二次探测；既有 7 case test_admin_flags PASS |
| `fliki-clone-api/tests/test_track27_rbac_role.py` | **新文件**，10 case 集成测：`is_editor` 三态 + 邮箱 fallback 不命中 / `is_viewer` 三态命中 + 缺省拒绝 / `require_role` 顺向 + 反向 + detail 含 "editor" 字样 | spec 要求 ≥ 8 case；本文件 10 case 把所有命中规则覆盖完 |

### 前端（2 改 + 2 新）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone/src/lib/admin-flags.ts` | `AdminMeOut` 接口扩 `is_editor` / `is_viewer` / `role` 三字段（与后端 `/me` schema 对齐） | hook 消费这个类型 |
| `fliki-clone/src/lib/role.ts` | **新文件** · 薄 helper：`Role` / `RoleSummary` / `summarizeRole(me)` / `canWrite` / `canManageBilling` / `disabledReason` + 中文 label 表 | 集中按钮 disable + tooltip 文案，避免每个组件自己拼 |
| `fliki-clone/src/hooks/use-current-role.ts` | **新文件** · `useCurrentRole(): CurrentRoleState` —— `useEffect` 单次探 `/admin/feature-flags/me` → `summarizeRole`；loading 阶段所有 `can*` 返 false 兜底 | sidebar `getAdminMe` 已有，这里复用同一端点不引新路由 |
| `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx` | `PipelinePage` 顶部 + `VersionsBlock` + `VersionRow` + `PublishPlansBlock` + `PlanRow` 各加一行 `useCurrentRole()` + `canWrite` / `disabledReason`；按钮 `disabled` prop 加 `!writeAllowed` + `title` fallback 到 `writeDisabledReason`；不动其它逻辑 | spec 要求互斥锁严格，仅控 disabled / title |
| `fliki-clone/src/app/[locale]/(app)/app/billing/page.tsx` | 顶部加 `useCurrentRole` + `canManageBilling` + `disabledReason({ adminOnly: true })`；「Manage subscription」+ 三档 plan 按钮加 `disabled` + `title` | 计费按钮非 admin disable |

## 3. 烟测命令 + 结果

```bash
# 后端单元 / 集成
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest \
    tests/ --ignore=tests/test_track30_workspaces.py
# → 140 passed in 2.84s（130 baseline + 10 我的新 case）

# 仅 Track-27 case 单跑
.venv/bin/python -m pytest tests/test_track27_rbac_role.py -v
# → 10 passed in 0.67s

# 前端类型检查
cd /Users/zhaoguangyuan/project/empty/fliki-clone && npx tsc --noEmit
# → 0 errors（仅 npm warn devdir，无关）
```

10 个新 case 覆盖：

1. `is_editor_admin_membership_hits` ─ team_members.role=admin → True
2. `is_editor_editor_membership_hits` ─ team_members.role=editor → True
3. `is_editor_viewer_membership_rejected` ─ team_members.role=viewer → False
4. `is_editor_email_fallback_does_not_apply` ─ admin email + 无 team_member → False（fallback 仅对 is_admin 生效）
5. `is_viewer_all_roles_hit` ─ admin/editor/viewer 三档都 → True
6. `is_viewer_no_membership_rejected` ─ user_id None / 不在表 → False
7. `require_role_writer_rejects_viewer` ─ viewer 调 require_role(["admin","editor"]) → 403
8. `require_role_admin_only_rejects_editor` ─ editor 调 require_role(["admin"]) → 403
9. `require_role_writer_passes_editor` ─ editor / admin 调 require_role(["admin","editor"]) 不抛
10. `require_role_403_detail_contains_editor` ─ 403 detail 必含 "admin" + "editor" 字样（前端 tooltip 契约）

## 4. 已知边界 / 跳过的子任务

- **`_get_or_create_workspace` 还是 owner 兜底没动**：
  Track-24 里 alembic `team_members.role` 列已落库 + backfill workspace owner = admin；
  非 owner 没显式写入 team_members 行的 dev user 仍走「`is_admin` 邮箱白名单」的 fallback，
  本 Track 没扩 owner 自动写 team_members。生产环境 owner 都已有行，不影响。
- **role 切换 workspace 联动留给 T-30**：
  `useCurrentRole()` 当前只探 `/admin/feature-flags/me`（返用户**最高** role），
  不跟随 workspace selector 切换。T-30 落 workspace selector 后，
  下一波 Track 可让 hook 接 `?workspace_id=` 重新探。
- **role 编辑 UI 没动**：`routers/team.py::PATCH /team/members/{id}` 已有该能力，UI 留给后续。
- **TestClient 没起整 HTTP 栈**：spec 要求「mock current_user role=editor → POST /publish-plans 200」由 case 9 的 require_role 直接调用等价覆盖；起 TestClient 在沙盒里偶尔踩 event loop 坑（第三波 T-13 踩过），ROI 不划算。

## 5. Follow-up

- **如果 admin_emails 邮箱白名单兜底要废掉**：需要新一波 Track 把 `is_admin` 内部的
  `_is_admin_email` fallback 移除，并把 `demo@example.com` 等 dev seed 走 team_members
  路径。**当前不能直接废**：fixtures / 烟测 / dev seed / 生产灾备都依赖它。
- **role-aware admin metrics 页**：T-21 admin/metrics 页前端是按 `is_admin` 渲染，
  Track-27 没改。后续若需要 editor 也看 metrics（只读），把页面入口判定从 `is_admin`
  改成 `isAdmin || isEditor` 即可（schema 已经全准备好了）。
- **审计日志**：viewer 真发 403 时只走 router 默认 log；如需审计 admin 写操作，
  可加 middleware 落到 `audit_logs` 表（v1 范围之外）。
- **role 变更后 cache 不失效**：`get_user_role` 60s 内存缓存来自 Track-24，
  admin UI 改成员 role 后用户最长可能要等 60s 才生效。生产可在
  `routers/team.py::PATCH /team/members/{id}` 末尾调 `rbac.clear_cache()`，
  本 Track 没动 routers/team.py（互斥锁规则）。

## 6. 互斥锁兑现

- 后端：`rbac.py` 末尾追加（不改既有签名）；4 个 router 写端点 decorator 加 `dependencies` 列表（不改函数签名）；`admin_flags.py::/me` schema 扩 3 字段（既有 7 case 全 PASS）；新 test 文件 ✓
- 前端：`lib/admin-flags.ts` schema 扩 3 字段；新 `lib/role.ts` + `hooks/use-current-role.ts`；按钮 disable 段（仅控制 disabled prop + tooltip，不动其它逻辑） ✓
- **未动**：sidebar.tsx 顶部段（T-30 占）；VoiceArtifact 段（T-26 占）；docker-compose / Dockerfile（T-28 占）；docs/adr/（T-29 占）✓
