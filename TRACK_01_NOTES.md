# Track-01 · 凭证 Fernet 加密 - 完成 Notes

> 分支：`track-01-credentials-fernet`
> 完成时间：2026-05-05 11:55
> 负责 agent：Cursor Agent (Claude Opus 4.7)

## 目标回顾

`platform_credentials.access_token` / `refresh_token` 当前 plain text 落库；用 Fernet
对称加密落库 + 读时透明解密；现有数据用一次性脚本升级；KEY 缺失时优雅降级。

## 改了哪些文件 + 为什么

| 文件 | 性质 | 关键改动 |
|---|---|---|
| `fliki-clone-api/.env` | modify | 追加 `PUBLISH_CREDENTIAL_FERNET_KEY=2u-ZDXz_…`（dev 用，gitignored）+ 注释说明生成方式与 fallback 行为 |
| `fliki-clone-api/app/config.py` | modify | 加 `publish_credential_fernet_key: str = ""` 字段；加 `field_validator` 校验：空串放行 / 非空必须是 url-safe base64 且解码后 32 字节，否则启动早 fail |
| `fliki-clone-api/app/services/publishing/credentials.py` | modify | 新增 `_get_fernet()` 惰性加载（缓存 + 一次性 warning）/ `_encrypt(token)` / `_decrypt(token)` / `_looks_encrypted(token)`；`upsert_credential` / `update_after_publish` 写库前 `_encrypt`；`_row_to_payload` 读出后 `_decrypt`；解密失败（老 plain text 行）原样返回 fallback；KEY 缺失时全链路 plain text + warning 一次 |
| `fliki-clone-api/scripts/migrate_encrypt_creds.py` | **new** | 一次性升级脚本：扫所有行，未加密的 `_encrypt` 后写回；`_looks_encrypted` 跳过已加密行实现幂等；支持 `--dry-run`；KEY 未配置时退码 2 不乱写 |
| `fliki-clone-api/requirements.txt` | modify | 显式加 `cryptography>=41`（之前已通过 `python-jose[cryptography]==3.3.0` 间接依赖到 46.x，这里显式声明便于审计 / pip-tools / 生产 lockfile）|

**严格遵守互斥锁**：未碰 `alembic/`、未碰其他 `services/`、未改前端、未碰 `SESSION_HANDOFF.md`。
**未做**：alembic schema 改动、新加表、改 `publishing/executor.py` 业务逻辑。

## 设计要点

1. **平滑迁移**：`_decrypt` 解不出（老 plain text 行）→ 原样返回 + `info` 日志（非 warning，避免 publish 链路刷屏）。这样 KEY 设好后无需立刻跑 migrate；正常 publish 不会炸。彻底升级再跑脚本。
2. **KEY 缺失向后兼容**：模块级 `_WARNED_NO_KEY` 标志确保 warning 只刷一次；`_encrypt` / `_decrypt` 直接返原值；老库 / 新机器没配 KEY 也能继续工作。
3. **upsert 时 refresh_token 保留旧值的语义**：`existing.refresh_token` 来自 `_row_to_payload`（已解密的 plain text），所以再次 encrypt 写回不会双层加密。
4. **migrate 幂等保证**：`_looks_encrypted(token)` 用同一个 fernet key 试解密，能解出说明已是密文，跳过；这样可重复跑多次。
5. **validator 早 fail**：非 base64 / 解码非 32 字节 → 启动报 ValidationError；避免后端能起来但每次写库 500。
6. **Fernet KEY 缓存**：用 `_FERNET_CACHE: dict[str, Fernet]` 按 key 字符串缓存，避免每次写库重建 Fernet 对象（hot path 可能高频）。

## 烟测结果

### 1. 单元级 _encrypt / _decrypt（KEY 已配）

```text
KEY len: 44 (=44 bytes url-safe base64)
encrypt('plain') → 'gAAAAA...' (120 bytes)
decrypt(enc) == plain                  ✓ roundtrip
_looks_encrypted(enc) == True          ✓
_looks_encrypted(plain) == False       ✓
decrypt(plain) == plain                ✓ fallback for old plain rows
encrypt(None) == None                  ✓
decrypt(None) == None                  ✓
```

### 2. 单元级 fallback（KEY 留空）

```text
WARNING: PUBLISH_CREDENTIAL_FERNET_KEY 未配置；... 将以 plain text 落库
encrypt('plain-secret') → 'plain-secret'   ✓ pass-through
decrypt('plain-secret') → 'plain-secret'   ✓ pass-through
_looks_encrypted('gAAAAA…') → False        ✓ (no KEY → can't verify)
```

### 3. validator 拒绝非法 KEY

```text
PUBLISH_CREDENTIAL_FERNET_KEY="not-base64!"
  → ValidationError: 必须是 url-safe base64 编码          ✓

PUBLISH_CREDENTIAL_FERNET_KEY="aGVsbG8="  (5 bytes)
  → ValidationError: 解码后必须是 32 字节                  ✓
```

### 4. 端到端 DAO + DB 烟测（10 步全过）

环境：本机 PG `fliki` 库；FK 约束要求真实 user_id → 用 `demo-user-001` + 伪平台名
`smoke-legacy-XXXXXX` / `smoke-new-XXXXXX` 避免污染真实 youtube/bilibili 行。

```text
STEP 1: 直接 INSERT plain text 行（模拟 v1 老数据）          ✓
STEP 2: upsert_credential 写新行                             ✓
STEP 3: 库里 raw access_token / refresh_token = gAAAAA...    ✓ (140 bytes ciphertext)
        legacy 行还是 'LEGACY_PLAIN_AT_xyz' (19 bytes plain) ✓
STEP 4: get_credential 透明解密；legacy plain 也能 fallback   ✓
STEP 5: dry-run migrate 报 "would upgrade legacy"            ✓ (DB 未动)
STEP 6: 真跑 migrate → upgraded: 1 / already: 1              ✓
STEP 7: 库里 legacy 行变 gAAAAA... (120 bytes)；解密回原文    ✓
STEP 8: 再跑 migrate → upgraded: 0 / already: 2              ✓ 幂等
STEP 9: update_after_publish 写新 access；refresh 保留        ✓ 新 access 也是密文
STEP 10: revoke 删行；再 revoke 返 False                     ✓
```

### 5. backend 重启验证

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```text
INFO: Application startup complete.
INFO: Uvicorn running on http://127.0.0.1:8000
GET /openapi.json → 200 OK
settings.publish_credential_fernet_key 已加载 (44 chars, prefix '2u-ZDX')
```

新 settings 字段 + validator + credentials 模块加载全部 OK；老 backend pid 59135 已 kill；
新进程监听同端口（请求方依赖 cookie 不需重新登录）。

## 已知边界 / 跳过的子任务

1. **未涉及 publish_plans / publish 业务流**：按互斥锁要求只动 credentials.py；YouTube
   真发安全闸门是 Track-02 的事。executor.py、adapters/ 没动。
2. **未跑真 OAuth 流程**：本机没配 `GOOGLE_CLIENT_ID/SECRET`，且 OAuth callback 落库走的
   就是 `upsert_credential` 这条加密路径，覆盖率已被烟测保证（STEP 2 等价于 OAuth 成功后回写）。
3. **psql 工具不在 PATH**：用户 prompt 里要求 "psql 看 access_token 应是 gAAAAA..."；
   本机只装了 PG server 没装 client CLI。改用 `sqlalchemy.text('SELECT access_token FROM …')`
   直接拿 raw bytes 验证密文前缀，等价于 psql 直查（见 STEP 3 / STEP 7）。
4. **未做 KEY rotation**：当前实现单 KEY；未来要支持 key rotation 可以用
   `MultiFernet([new_key, old_key])`，KEY 列表从 `.env` 逗号分隔解析。留作 follow-up。

## Follow-up（建议下一步给协调者参考）

1. **生产部署**：`PUBLISH_CREDENTIAL_FERNET_KEY` 必须从环境变量 / Secret Manager 注入，
   不要写进 .env 进 docker image；KEY 丢失等同凭证全失效，建议双备份。
2. **alembic 列加注释**：可以给 `platform_credentials.access_token` 加一条注释 / migration
   把列宽从默认 String 改成 String(512)（密文比明文长 5x，140-bytes 量级，但 PG TEXT 列
   不受限；如果未来约束 schema 长度再说）。**本 Track 不动 schema**。
3. **MultiFernet KEY rotation**：见上。
4. **审计日志**：可以在 `_encrypt` / `_decrypt` 失败时上报 metric（如 `credentials_decrypt_fail`）
   让告警系统盯到漏迁移行；当前只 log。
5. **L-07 ADR-003 凭证加密策略**：把本 Track 的设计点（fallback 语义、迁移幂等、KEY 缺失行为）
   写进 ADR-003 沉淀。
6. **Track-10 灰度发布 / Track-11 Stripe 计费**（依赖 Track-01 完成）现在可以启动。

## 启动命令速查

```bash
# 验证 KEY
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api
.venv/bin/python -c "from app.config import get_settings; s=get_settings(); print(len(s.publish_credential_fernet_key))"

# 重启 backend（不带 --reload）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 一次性升级老明文行（幂等）
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api
.venv/bin/python scripts/migrate_encrypt_creds.py --dry-run   # 先 dry
.venv/bin/python scripts/migrate_encrypt_creds.py             # 真跑

# 生成新 KEY（一次性）
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
