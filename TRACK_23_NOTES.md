# Track-23 · ADMIN_EMAILS 从 env 直读迁回 `Settings.admin_emails`

> 分支：`track-23-admin-emails-settings`
> 基线：`ff48c75 docs(agents): 第五波 Backlog（T-20/21/22/23/24/25 完整卡片）`
> alembic head：`c3d4e5f6a7b8`（不动）
> 全量 pytest：**95 PASS**（89 baseline + 6 新增）

## 1. 改了哪些文件 + 为什么

### 1.1 `fliki-clone-api/app/config.py`

新加一个字段：

```python
# Admin（Track-23）
admin_emails: str = "demo@example.com"
```

- **为什么是 `str` 而不是 `list[str]`**：pydantic-settings 自动从
env `ADMIN_EMAILS` 读，env 天然是字符串；用 `str` 让运维 `.env` 写
`ADMIN_EMAILS=ops@x.com,oncall@y.com` 即可，不需要 JSON 数组语法。
解析（split/strip/lower/去空/set 化）由 `_allowed_admins` 内部完成。
- **缺省 `demo@example.com`**：与 `tests/conftest.py` 的 demo user
fixture 一致，本地直接 `pytest` / `make dev` 开箱可测；生产 env 必须
显式覆盖。
- **位置选择**：插在「Stripe（Track-11）」段之前，避开 SMTP / Email 段
以**不踩 Track-22 互斥锁**（T-22 同期会改 `mail_`* 区附近加 SMTP_ 字段）。

### 1.2 `fliki-clone-api/app/routers/admin_flags.py`

`_allowed_admins()` 从 `os.environ.get("ADMIN_EMAILS", "")` 切到
`get_settings().admin_emails`：

```python
def _allowed_admins() -> set[str]:
    raw = get_settings().admin_emails or ""
    items = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if items:
        return items
    return {_FALLBACK_ADMIN_EMAIL}  # "demo@example.com"
```

- 删掉文件级 `import os`（不再需要）
- 抽出 `_FALLBACK_ADMIN_EMAIL = "demo@example.com"` 模块常量，避免
字符串散落在多处，方便后续 Track-24（RBAC）替换 fallback 行为
- `_is_admin_email` / `_require_admin` / `admin_self_check` / `cost.py`
里的 `_resolve_query_tenant` **零 API 改动**——它们都依赖
`_allowed_admins` / `_is_admin_email` 这层间接，因此外层
Track-10 / 14 / 18 既有行为天然零回归。
- 顶部 docstring 改写：把「Track-01 互斥锁占了 config.py」过期理由
替换成「迁移说明（Track-23）」+ 指向 Track-24 RBAC follow-up。

### 1.3 `fliki-clone-api/.env.example`

新增 Track-23 段：

```
# ── Admin 邮箱白名单（Track-23）───────────────────────────────────────────
ADMIN_EMAILS=demo@example.com,you@example.com
```

让运维拿到 `.env.example` 第一眼就知道这一项；不写 / 留空都自动 fallback。

### 1.4 `fliki-clone-api/tests/test_admin_flags.py`（T-14 既有 7 case）

补 3 处 `get_settings.cache_clear()`：

- `admin_env` fixture（`monkeypatch.setenv` 后 + teardown 各一次）
- `test_is_admin_email_default_demo`（`monkeypatch.delenv` 后）
- `test_is_admin_email_env_overrides_default`（`monkeypatch.setenv` 后）

**为什么必须**：pydantic-settings 在 `Settings()` **init** 时一次性读 env；
`get_settings()` 又有 `@lru_cache`，因此 monkeypatch.setenv **不会**影响
已缓存的 settings 实例。Track-23 之前 `_allowed_admins` 直读
`os.environ.get` 不受这个影响；切到 settings 后必须显式 `cache_clear()`
才能让下次调用拿到带新 env 的全新 `Settings()` 实例。

7 case T-14 行为零变更，仅基础设施层补缓存 invalidate。

### 1.5 新文件 `fliki-clone-api/tests/test_track23_admin_emails.py`（6 case）


| #   | case                                            | 覆盖点                                                    |
| --- | ----------------------------------------------- | ------------------------------------------------------ |
| 1   | `test_settings_default_admin_emails_is_demo`    | `Settings.admin_emails` 默认值 = `"demo@example.com"`     |
| 2   | `test_allowed_admins_fallback_when_env_missing` | env 缺省 → fallback `{"demo@example.com"}`               |
| 3   | `test_allowed_admins_single_email_from_env`     | env 单邮箱 + 大小写归一                                        |
| 4   | `test_allowed_admins_multi_email_with_spaces`   | 多逗号 + 空白 + trailing 逗号 + 大小写：split + strip + lower 全链路 |
| 5   | `test_allowed_admins_empty_string_fallback`     | env=`""` / `" "` / `" , , "` / `",,,"` 都 fallback demo |
| 6   | `test_is_admin_email_pipeline_with_settings`    | env 切新名单后，新邮箱命中 / 老 demo 失效 / 大小写不敏感                   |


每个 case 用统一 `_reset_settings(monkeypatch, env_value=...)` helper：
delenv/setenv → `get_settings.cache_clear()`，避免 case 顺序耦合。

## 2. 烟测命令 + 结果

### 2.1 全量 pytest（95 / 95）

```bash
cd /Users/zhaoguangyuan/project/empty-track23/fliki-clone-api
/Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest -v
# → 95 passed in 2.12s
```

- 89 baseline（Track-10 / 14 / 18 / ... 全保留）：✅ 全 PASS
- 6 新增 Track-23 case：✅ 全 PASS
- T-14 admin_env fixture 改造后 5 个 _require_admin / list_tenants /
CRUD case 仍 PASS（fixture 走 `monkeypatch.setenv` + cache_clear）

### 2.2 import + 行为烟测

```bash
.venv/bin/python -c "
from app.config import get_settings
from app.routers import admin_flags, cost
print('default =', get_settings().admin_emails)
print('_allowed_admins =', admin_flags._allowed_admins())
print('cost ↔ admin_flags 同源:', cost._is_admin_email is admin_flags._is_admin_email)
"
# → default = 'demo@example.com'
# → _allowed_admins = {'demo@example.com'}
# → cost ↔ admin_flags 同源: True
```

### 2.3 `make test` 警示（**与本 Track 无关**）

`Makefile::test` 走 system Python 3.10（`/Library/Frameworks/...`），
该解释器没装 `asyncpg` / 当前 SQLAlchemy 版本，跑 `app.database` import
就 `AttributeError: 'NoneType' object has no attribute 'group'`，**与本
Track 改动无关**（baseline 也炸）。本 Track 的烟测口径是 **venv pytest**
（与 SESSION_HANDOFF / 任务卡片基线一致）。

如要让 `make test` 也通：把 Makefile `pytest` 替换成
`.venv/bin/python -m pytest`（属于工程化改进，**不在本 Track 范围**）。

## 3. 已知边界 / 跳过的子任务

- **未碰 SMTP_ 字段**：协调者 backlog 卡片明示「与 T-22 共改 config.py，
T-22 加 SMTP_ 字段；本批先合 T-22 再合 T-23」。本 Track 仅在
Stripe 段之前插入 admin_emails 一字段，**完全避开** `mail`_* /
`mail_server` / `mail_port` 区域，给 T-22 留独立 patch 空间。
- **未升级到完整 RBAC**：`workspace_member.role` / `editor` / `viewer`
是 Track-24（L-05）的事；本 Track 只把 v1 邮箱白名单的「读源」从
env 切到 settings，行为完全等价。
- **未做 settings 字段校验**：没加 `field_validator` 校验邮箱格式
（比如必须含 `@`）。理由：fallback 已经兜住「解析为空回 demo」的
最坏情况；运维写错邮箱（如漏 `@`）会让 `_is_admin_email` 自然返
False，进入 403 路径，不会让后端崩。校验复杂化收益不高。
- **未删 `_FALLBACK_ADMIN_EMAIL` 常量留 Track-24 钩子**：当前模块常量
方便 Track-24 在 RBAC 上线后把 fallback 从「demo 邮箱」改成
「workspace owner 都算 admin」之类的策略，单点改动即可。

## 4. 后续 follow-up

### 4.1 协调者合并顺序（**关键**）

`app/config.py` 是 T-22 ↔ T-23 共改文件：


| Track                  | 改 config.py 的位置                | 互斥锁约定 |
| ---------------------- | ------------------------------ | ----- |
| T-22 (SMTP 落 settings) | `mail`_* 区 / 加 `smtp`_* 新字段    | 先合    |
| T-23 (本 Track)         | Stripe 段之前插 `admin_emails` 一字段 | 后合    |


**合并顺序：T-22 → main → T-23 拿到 main 后自动 rebase**：T-23 改的位置
（Stripe 之前）与 T-22 改的位置（Email/SMTP 段）完全错开，rebase 期望
**零冲突**；如果 T-22 重构了整段 config 类布局（比如把字段按 Section 归类），
最多需要把 Track-23 的 `admin_emails` 字段挪到 admin 章节即可，逻辑零变更。

如果协调者反向合（T-23 先 → T-22 后），后果一致只是 rebase 方向反过来；
但 backlog 卡片明示 T-22 → T-23 顺序，建议遵守。

### 4.2 上 production 前

- 真生产 env 把 `ADMIN_EMAILS` 显式覆盖为运维邮箱（不要让 fallback
[demo@example.com](mailto:demo@example.com) 留在生产白名单）。
- 把 `.env.example` 里的占位 `you@example.com` 删掉或改成实际指引。

### 4.3 Track-24 接力

- Track-24（L-05）真 RBAC 上线时，`_is_admin_email` 仍可保留作 admin
邮箱白名单兜底；新增 `rbac.get_user_role(user_id, workspace_id) == "admin"`
优先判定。
- 如果决定彻底废弃邮箱白名单，删掉 `Settings.admin_emails` +
`_allowed_admins` + `_is_admin_email` 即可，不会留孤儿引用
（`cost.py::_resolve_query_tenant` 调用点已知，明文重构即可）。

## 5. commit 信息（自检 git status）

`git status` 在交付前应为：

```
On branch track-23-admin-emails-settings
nothing to commit, working tree clean
```

✅ 已确认 working tree clean。