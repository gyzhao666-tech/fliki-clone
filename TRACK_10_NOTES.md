# Track-10 · 灰度发布 / canary 路由 — 交接 NOTES

## 概要

按 `tenant_id` hash 染色让一部分 tenant 走 `ArtAgent v4`（IP-Adapter），一部分走
`v3 prompt-only`；机制可复用到任意 agent 的版本切换（voice / video / publishing
后续直接复用 `feature_flags` 服务模块即可）。

## 新 alembic head

**`a1b2c3d4e5f6`**（顶 `9c2d4e5f6a7b`，新增 `feature_flags` 表）

```
$ .venv/bin/python -m alembic current
a1b2c3d4e5f6 (head)
```

## 改了哪些文件 + 为什么

### 后端 — 新增

| 文件 | 作用 |
|---|---|
| `fliki-clone-api/alembic/versions/20260505_1300_add_feature_flags.py` | 新表 `feature_flags(id, tenant_id, flag_name, value_json, created_at, updated_at)` + 唯一约束 `(tenant_id, flag_name)` + 普通索引；rev `a1b2c3d4e5f6`，down 顶 `9c2d4e5f6a7b` |
| `fliki-clone-api/app/models/feature_flag.py` | ORM `FeatureFlag`；`value_json` 是任意 JSON dict，语义不在 ORM 这一层定 |
| `fliki-clone-api/app/services/pipeline/feature_flags.py` | 核心服务：`get_flag` / `set_flag`（PG `INSERT ... ON CONFLICT` 原生 upsert）/ `delete_flag` / `load_for_tenant`（runner 一次性批量）/ `is_enabled`（核心染色判断，支持 `pct` / `enabled` / `variant` 三种 value 形态；hash 用 SHA-1 前 8 hex 取 mod 100，跨进程稳定） |
| `fliki-clone-api/app/routers/admin_flags.py` | Admin 路由：`GET /api/admin/feature-flags?tenant_id=...` / `GET /{tid}/{name}` / `PUT /{tid}/{name}` / `DELETE /{tid}/{name}`；admin gate 走 `user.email in ALLOWED_ADMINS`，邮箱来源 `os.environ['ADMIN_EMAILS']`（逗号分隔），fallback `demo@example.com`（避免越界改 `app/config.py`，Track-01 互斥锁） |

### 后端 — 修改（最小入侵）

| 文件 | 修改 |
|---|---|
| `fliki-clone-api/app/models/__init__.py` | 导入 `FeatureFlag` 让 alembic env 能 detect |
| `fliki-clone-api/app/services/pipeline/types.py` | `PipelineContext` 加 `feature_flags: dict[str, dict[str, Any]]` 字段（默认空 dict） |
| `fliki-clone-api/app/services/pipeline/runner.py` | `execute_step` build ctx 时多 4 行：`load_for_tenant(tenant_id) → feature_flags_map → 注入 ctx`；不影响其它路径 |
| `fliki-clone-api/app/services/pipeline/agents/art.py` | 入口加 12 行：读 `ctx.feature_flags['art_ipadapter_pct']`，缺省 → 默认 v4；存在 → `is_enabled(..., key=ctx.run_id)` 决定。命中 → 喂 anchor 给 `_generate_keyframes`（v4 IP-Adapter）；未命中 → anchor_url 置 None（v3 prompt-only，前缀注入仍生效）。outputs 多 2 字段：`canary_variant`（`v4` / `v3-prompt-only`）+ `canary_flag_value`（落库的原始 value，便于前端展示当前档位） |
| `fliki-clone-api/app/routers/__init__.py` | 注册 `admin_flags_router` |
| `fliki-clone-api/app/main.py` | `app.include_router(admin_flags_router, prefix=PREFIX)` |

## 灰度语义

flag 名 `art_ipadapter_pct`，value 形态约定（`is_enabled` 自动识别）：

- `{"pct": 0..100}` —— **百分比闸门**（烟测主用）
  - hash seed = `f"{tenant_id}|{flag_name}|{key}"`，SHA-1 前 8 hex mod 100
  - bucket `< pct` 视为命中；pct=0 全关；pct=100 全开
  - art.py 传 `key=ctx.run_id` → 同 tenant 不同 run 之间能稳定 50/50 分流
- `{"enabled": true/false}` —— 直接开关
- `{"variant": "v4"/"v3"/"off"}` —— 命名 variant；`""`/`"off"`/`"disabled"`/`"none"` 视为关

**默认行为**：tenant 没设 flag → 走 v4（向后兼容现有 art v4 行为，避免无声降级）。

## 烟测命令 + 结果

### 0. alembic upgrade

```
$ cd fliki-clone-api && .venv/bin/python -m alembic upgrade head
INFO  Running upgrade 9c2d4e5f6a7b -> a1b2c3d4e5f6, add_feature_flags
$ .venv/bin/python -m alembic current
a1b2c3d4e5f6 (head)
```

### 1. service 层（hash 染色稳定性 + CRUD）

跑完即删的 `_track10_smoke.py`：

```
=== Track-10 canary 烟测 ===
tenant_id=u:track10-smoke-tenant  flag=art_ipadapter_pct
pct=50  → 49.0% 走 v4 （期望 ~50%）              ✓
pct=100 → 100.0% 走 v4 （期望 100%）             ✓
pct=0   → 0.0% 走 v4 （期望 0%）                 ✓
delete 后 get_flag → None （期望 None）           ✓
二次 delete 返 False                               ✓
{"enabled": true/false} 形态                       ✓
{"variant": "v4"/"off"} 形态                       ✓
hash 稳定性（同 run 多次评估同结果）                 ✓
=== ALL PASS ===
```

### 2. 端到端通过 ArtAgent（mock gateway 不发外网）

跑完即删的 `_track10_e2e_smoke.py`：

```
=== Track-10 e2e 烟测（ArtAgent canary 入口）===
flag 缺失 → canary_variant=v4 ✓
pct=100 → canary_variant=v4, shot keyframes 都喂 image_url ✓
pct=0 → canary_variant=v3-prompt-only, shot keyframes 都不喂 image_url ✓
pct=50 → 30 次不同 run，v4 占比 70.0% （期望 ~50%，小样本 ±20% 噪声）
=== ALL PASS ===
```

### 3. 全量 pytest 防回归

```
$ .venv/bin/python -m pytest -q
...............................                                          [100%]
31 passed in 0.63s
```

### 4. Admin 路由（手工 curl 模板）

```bash
# 假设 demo@example.com 已登录拿到 cookie token
TID="u:demo-user-001"

# 设 50% 灰度
curl -X PUT -H "Cookie: token=$TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":{"pct":50}}' \
  http://127.0.0.1:8000/api/admin/feature-flags/$TID/art_ipadapter_pct

# 读
curl -H "Cookie: token=$TOKEN" \
  http://127.0.0.1:8000/api/admin/feature-flags/$TID/art_ipadapter_pct

# 列该 tenant 全部 flag（含 known_flags 文档）
curl -H "Cookie: token=$TOKEN" \
  "http://127.0.0.1:8000/api/admin/feature-flags?tenant_id=$TID"

# 改成全开
curl -X PUT -H "Cookie: token=$TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":{"pct":100}}' \
  http://127.0.0.1:8000/api/admin/feature-flags/$TID/art_ipadapter_pct

# 关
curl -X PUT -H "Cookie: token=$TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":{"pct":0}}' \
  http://127.0.0.1:8000/api/admin/feature-flags/$TID/art_ipadapter_pct

# 删
curl -X DELETE -H "Cookie: token=$TOKEN" \
  http://127.0.0.1:8000/api/admin/feature-flags/$TID/art_ipadapter_pct
```

## 已知边界 / 跳过的子任务

1. **admin 鉴权简化**：当前只看 `user.email in ALLOWED_ADMINS`（env 来源 `ADMIN_EMAILS=...`，
   fallback `demo@example.com`）。未引入完整 RBAC（L-05 长尾）。
2. **Settings 字段暂留 env 直读**：因为 Track-01 互斥锁占了 `app/config.py`，
   `ADMIN_EMAILS` 只能用 `os.environ` 直读；后续协调者合并后建议把它正式迁到 `Settings`。
3. **flag 的 value schema 不强制校验**：admin PUT 接受任意 JSON object；
   `is_enabled` 自动识别已知形态（`pct` / `enabled` / `variant`），其它形态默认返 `False`。
   后续可以加 per-flag JSON Schema 校验。
4. **没做前端 UI**：admin panel 暂以 curl/HTTP API 操作；
   建议 follow-up 在 settings 页加一个「Admin · Feature Flags」tab。
5. **没改 video.py / publishing**：互斥锁严守；这些 agent 后续要做 canary 时
   只需 `pipeline_feature_flags.is_enabled(ctx.tenant_id, "<your_flag>", flags=ctx.feature_flags)`
   即可复用，机制完全通用。
6. **真实端到端 video_full 烟测要求外网 + DB 真 tenant**：本 NOTES 的烟测都用
   mock gateway 完成，证明决策路径与传参形态正确；要在 PG 库里真跑，使用上文的
   curl 模板（admin 路由）+ `POST /api/pipelines/{template}/start` 即可，
   pct=50 时跑两次 video_full 应有一次 art outputs.canary_variant=v4，一次 v3-prompt-only。

## Follow-up

1. 把 `ADMIN_EMAILS` 迁到 `Settings`（Track-01 合并后）
2. 给 voice / video / publishing agent 加各自的 canary flag（同机制复用）
3. 前端「Admin · Feature Flags」管理面板（GET list + PUT 滑块）
4. ProductionPanel/Pipeline 顶部展示当前 run 的 `outputs.art.canary_variant` 徽标，
   方便人工对比效果时一眼看出走的是哪一档
5. flag 写库时打 audit log（`who / when / tenant / flag / from / to`），便于 incident 复盘

## 互斥锁声明

- ✅ alembic 迁移槽：本 Track 独占（rev `a1b2c3d4e5f6`）
- ✅ 没改 publishing / quota / 其他 agent / 前端
- ✅ 没改 `.env` / `app/config.py`（Track-01 互斥锁严守）
- ✅ 没改 `pipeline/page.tsx`
- ✅ 完全前后端无冲突；二波其它 Track 不会与本 Track 文件交集
