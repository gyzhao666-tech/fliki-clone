# Track-14 · 前端 Admin · Feature Flags 管理面板

> 分支：`track-14-admin-flags-ui`（worktree：`/Users/zhaoguangyuan/project/empty-track14`）
> 基线：`main` @ `68fccd3`
> alembic：不动（不占迁移槽）

> ⚠️ 本 NOTES 由协调者补写：agent 工作完成且 pytest 48/48 PASS，但忘了 commit + 写 NOTES。
> 协调者已用 `git add -A && git commit` 把所有改动收口到本分支。

## 改了哪些文件 + 为什么

### 后端

| 文件 | 改动 | 为什么 |
|---|---|---|
| `fliki-clone-api/app/routers/admin_flags.py` | 加 `_is_admin_email(email)` 公共判定函数；新加端点 `GET /api/admin/feature-flags/me`（任何登录用户可调，返 `{is_admin, email}`，让前端 sidebar 探测是否渲 admin 入口而不抛 403）+ `GET /api/admin/feature-flags/tenants`（admin 限定，按 tenant_id 聚合 SELECT + flag_count；返 `tenants[]` + `known_flags` hint） | `/me` 单独留是为了不越界改 `routers/auth.py` 的 UserOut；`/tenants` 给 admin UI 顶部 tenant 选择器用，避免前端瞎猜 |
| **新** `fliki-clone-api/tests/test_admin_flags.py` | 7 个 case：`_is_admin_email` fallback / env 覆盖；`_require_admin` 非命中 403；`/me` admin/非 admin 都 200；`/tenants` 按 tenant_id 聚合；CRUD round-trip（PUT → GET single → list → DELETE） | 用 `SimpleNamespace` 当 fake user，纯函数级单测；不起 TestClient（避开 sandbox event loop 问题） |

### 前端

| 文件 | 改动 | 为什么 |
|---|---|---|
| **新** `fliki-clone/src/lib/admin-flags.ts`（111 行）| TS 类型 `AdminMeOut` / `TenantSummary` / `FeatureFlagOut`；fetch helper `getAdminMe` / `listAdminTenants` / `listTenantFlags` / `setTenantFlag` / `deleteTenantFlag` | 把 `/api/admin/feature-flags/*` 5 端点封装成强类型 client；与 `lib/production.ts` 同款风格 |
| **新** `fliki-clone/src/app/[locale]/(app)/app/admin/feature-flags/page.tsx`（968 行）| Admin 管理面板：顶部 tenant 选择器（拉 `/tenants`）；表格列 flag_name / value（pct 滑块 0-100 / enabled toggle / variant 下拉，自适应渲染）/ updated_at / Apply / Delete；「新增 flag」dialog 从 `known_flags` 选 + 形态选；变更前后 toast 提示 | 把 Track-10 留下的 HTTP API 包装成可视化面板，admin 不用再 curl |
| `fliki-clone/src/components/app-shell/sidebar.tsx` | mount 时 fetch `getAdminMe`；命中 admin 时多渲一个「Admin · Feature Flags」入口（路径 `/app/admin/feature-flags`） | 非 admin 不会看到入口（`/me` 探测安静返 403-free），避免开发台 UI 噪音 |

## 烟测

```bash
cd /Users/zhaoguangyuan/project/empty-track14/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest -q
# → 48 passed in 1.68s（基线 41 + 本 Track 7）
```

未跑：
- 真启 backend + 浏览器手测（agent 没起服务）；建议合并后协调者用 demo@example.com 登录访问 `/app/admin/feature-flags` 看 admin 入口 + tenant 选择 + 滑块 Apply 闭环

## 互斥锁守住

- ✅ 不动 alembic（T-16 独占本波迁移槽）
- ✅ 不动 `.env` / `app/config.py`（`ADMIN_EMAILS` 用 `os.environ` 直读，与 Track-10 行为一致）
- ✅ 不动 `pipeline/page.tsx`（T-13 独占 PlanRow）
- ✅ 不动 `use-publish-plan-stream.ts`（T-13 / T-17 共占）
- ✅ 不动 `events.py`（T-17 独占）
- ✅ 不动 `dlq.py`（T-15 独占）
- ✅ 不动 `services/billing/` / `webhook_handlers.py`（T-16 独占）

## Follow-up

- [ ] L-13 把 `ADMIN_EMAILS` 从 env 直读迁回 `Settings`（Track-01 互斥锁已解除，只是没人去做）
- [ ] 后端 audit log 落库（admin 改 flag 时写一条 `feature_flag_audit` 行：who/when/from/to）
- [ ] L-05 真 RBAC：把邮箱白名单升级为 workspace member role（editor/viewer/admin）
- [ ] 前端 admin 面板：批量改（一次给多个 tenant 设同一 flag）/ 撤销（误改回滚）
