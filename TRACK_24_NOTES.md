# Track-24 · L-05 真 RBAC（workspace member role）

> 分支：`track-24-rbac-workspace-role`
> 基线：`df587bc`（第五波合并完成的状态）
> alembic 头：`c3d4e5f6a7b8` → 本 Track 推进到 **`d4e5f6a7b8c9`**
> 完成时间：2026-05-05

## 目标回顾

把 Track-10/14/18/23 一直沿用的「邮箱白名单 admin」升级为基于
`team_members.role`（`admin` / `editor` / `viewer`）的 RBAC v1。
Track-23 已把 `admin_emails` 落到 `Settings.admin_emails`；本 Track 在其上做
**fallback 兜底**：先查 `team_members.role`，不命中再走邮箱白名单
（保留 `demo@example.com` 兼容 dev fixtures / seed）。

## 改了哪些文件

### 1. `fliki-clone-api/alembic/versions/20260505_1700_add_team_member_role.py`（新）

- rev `d4e5f6a7b8c9` 顶 `c3d4e5f6a7b8`（独占第六波迁移槽）
- 关键发现：`team_members.role` 列**早就在 initial_schema** 里（VARCHAR(20) NOT NULL，
  无 server_default、无索引）。所以本迁移做的是「让它真正生效」三件事：
  1. `ALTER COLUMN role SET DEFAULT 'editor'`（元数据操作不锁表）
  2. 加普通索引 `ix_team_members_role`（rbac.is_admin workspace 缺省路径会用）
  3. 一次性 backfill：`workspace.owner_id` 命中的 team_member 行 → `admin`
- `down`：撤索引 + 撤 server_default + role 全部归一为 `editor`（不能精确还原 backfill 之前每行的值，按 RBAC v1 简化语义全部归一）

### 2. `fliki-clone-api/app/services/auth/__init__.py`（新）+ `rbac.py`（新）

- `get_user_role(user_id, workspace_id) -> "admin"|"editor"|"viewer"|None`
- `is_admin(user_id, *, workspace_id=None, email=None) -> bool` 三路径：
  1. **显式 workspace_id**：`SELECT role FROM team_members WHERE user_id=:u AND workspace_id=:w` → role=='admin'
  2. **workspace_id 缺**：`SELECT role FROM team_members WHERE user_id=:u AND role='admin' LIMIT 1`
  3. **都不命中** → fallback `_is_admin_email(email)`（保留 `demo@example.com`）
- 60s 内存缓存（与 `services/pipeline/tenant.py` 同 pattern；key=`(user_id, workspace_id_or_None)`）
- `clear_cache()` 测试钩子
- 邮箱白名单逻辑在本模块**复述**了一遍（同样从 `Settings.admin_emails` 读 + demo fallback），
  避免与 `app.routers.admin_flags` 形成 import 循环；两边互为冗余兜底，函数语义完全一致

### 3. `fliki-clone-api/app/routers/admin_flags.py`

- `_require_admin` 改为走 `rbac.is_admin(current_user.id, email=current_user.email)`
- 抽 `_is_admin_user(current_user)` 让 `_require_admin` 与 `/me` 端点共享判定（避免分支漂移）
- `_is_admin_email` **保留不删**（rbac 的 fallback 调用方 + 旧测试 + 兜底兼容）
- `/me` 端点 `is_admin` 字段改为 `_is_admin_user(current_user)`
- 顶部 docstring 同步说明 Track-24 升级语义；URL / 返回 schema 完全不变

### 4. `fliki-clone-api/app/routers/cost.py`

- `_resolve_query_tenant` 内部 admin 判定从 `_is_admin_email(email)`
  → `rbac.is_admin(current_user.id, email=current_user.email)`
- import 行 `from app.routers.admin_flags import _is_admin_email`
  → `from app.services.auth import rbac`
- 顶部 docstring Security 段落同步说明
- `/api/cost/summary`、`/api/cost/recent`、`/api/cost/timeseries` 的 URL / 返回 schema 完全不变

### 5. `fliki-clone-api/tests/test_track24_rbac.py`（新；10 case 全 PASS）

| # | case | 覆盖点 |
|---|---|---|
| 1 | `test_alembic_role_column_default_and_index` | DB schema 状态：role 列 server_default + 索引存在 |
| 2 | `test_team_member_default_role_editor` | 直接 SQL 插入不指定 role → 落 `editor`（server_default 生效） |
| 3 | `test_workspace_owner_backfilled_admin` | backfill SQL 把 owner 的 editor 行升级成 admin |
| 4 | `test_get_user_role_three_states` | admin / editor / 不在 workspace 三状态 |
| 5 | `test_is_admin_email_fallback_when_no_membership` | DB 路径全 miss → 邮箱白名单兜底；user_id=None 也能跑 |
| 6 | `test_is_admin_via_team_member_explicit_workspace` | 显式 workspace_id：role=admin → True；role=editor + 邮箱不命中 → False |
| 7 | `test_is_admin_via_team_member_any_workspace` | workspace_id 缺省：遍历用户 admin 命中 |
| 8 | `test_is_admin_cache_ttl_behavior` | 首查写缓存；改 DB 不立刻反映；clear_cache 后立刻反映 |
| 9 | `test_require_admin_integration_admin_email` | _require_admin：邮箱白名单兜底通过；非命中 403 |
| 10 | `test_require_admin_integration_team_member` | _require_admin：邮箱白名单不命中也能因 role=admin 通过（**核心新语义**） |

> 卡片要求 8+ case，本 Track 实测 10 case，把「team_member 显式 workspace」与
> 「team_member 缺省 workspace 遍历」两条路径分开测，避免一条 case 兜两件事。

## 烟测结果

```
$ make test
...
130 passed in 2.52s
```

- 基线 120 PASS（df587bc）→ 本 Track 130 PASS（+10 新 case），**0 退化**
- alembic upgrade → downgrade -1 → upgrade 双向迁移可逆，head 稳定回到 `d4e5f6a7b8c9`
- DB schema 验证：`team_members.role` 有 `'editor'::character varying` server_default + `ix_team_members_role` 索引
- 老 `tests/test_admin_flags.py` 7 case 完全没改也全 PASS
  （rbac.is_admin 在 fixture 用的 `fake-uid` 没有 team_members 行 → DB 路径 miss → 走邮箱白名单 fallback，与原行为等价）

## 互斥锁遵守情况

- ✅ alembic 第六波本 Track 独占 rev `d4e5f6a7b8c9`，未改其它迁移槽
- ✅ `models/team.py::TeamMember.role` Python-side default 仍是 `editor`（与 server_default 一致），未改字段定义
- ✅ 新模块 `services/auth/rbac.py` 独占
- ✅ `routers/admin_flags.py::_require_admin` 函数体小段独占；`_is_admin_email` 保留不删（fallback 兜底兼容）
- ✅ `routers/cost.py::_resolve_query_tenant` 函数体小段独占
- ✅ 不动前端（`lib/admin-flags.ts::getAdminMe` 返 schema 不变；后端 is_admin 判定升级即可）
- ✅ 不动 `pipeline/page.tsx`、不动 `.env` / `app/config.py`
- ✅ 不更新 `SESSION_HANDOFF.md`（由协调者统一）
- ✅ 完成代码后 `git status` working tree clean（T-14 教训：commit 完整性）

## 已知边界 / 跳过的子任务

- v1 只识别「admin vs 非 admin」；`editor` / `viewer` 实际权限分级是 L-05 真做时的事
  （完整 RBAC：哪些 endpoint editor 可调、哪些 viewer 只读）
- workspace 切换 UI 不做（前端用第一个有权限的 workspace 即可）
- `_user_has_admin_membership` 用 `WHERE user_id=:u AND role='admin' LIMIT 1` 命中即返；
  没做「哪个 workspace 的 admin」明细追踪。需要时再起 `list_admin_workspaces(user_id)` helper
- rbac 模块**复述**了一遍 `_is_admin_email` 逻辑（避免与 admin_flags 循环 import）；
  两边都从 `Settings.admin_emails` 读 + demo fallback，行为等价；如未来要再演进
  邮箱白名单语义（如加正则、加域名通配），需要同步两处或抽到第三方模块（`services/auth/email_acl.py`）

## Follow-up（给协调者）

1. **合并顺序**：本批第六波只有 Track-24 占 alembic 槽，无前置依赖；T-19/T-20 走外部
   依赖 / 协调者自跑路径，不与本 Track 冲突
2. **合并后**：协调者把 SESSION_HANDOFF.md 第 7 节「admin 判定流程」一句话带过
   （从「邮箱白名单」→「team_members.role + 邮箱白名单 fallback」），不需要改前端章节
3. **合并后烟测**：
   ```bash
   cd fliki-clone-api
   .venv/bin/python -m pytest tests/test_track24_rbac.py -v   # 10 PASS
   .venv/bin/python -m pytest tests/test_admin_flags.py -v    # 7 PASS（无回归）
   .venv/bin/python -m pytest -q                              # 130 PASS
   ```
4. **重启 backend**（pid 30876 还没拉新代码）：
   ```bash
   kill 30876
   cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
     .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
5. **L-05 真做时**接入点：`services/auth/rbac.py::get_user_role` 已经返完整 role 字符串，
   可直接派生 `can_edit` / `can_view` / `can_publish` 等行为权限矩阵
