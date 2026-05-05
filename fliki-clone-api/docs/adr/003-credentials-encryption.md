# ADR-003：发布平台凭证加密策略

- 状态：Accepted
- 日期：2026-05-05
- 决策人：fliki-clone 团队
- 关联 Track：Track-01（Fernet 加密 platform_credentials）
- 关联文档：`SESSION_HANDOFF.md`、`docs/adr/004-multi-platform-publish-sla.md`

---

## 背景

发布执行器 v1（Track-02 / Track-03 / Track-13 / Track-15）落地后，第三方平台 OAuth 凭证（YouTube `access_token` / `refresh_token`）必须长期落库，
单纯靠 Postgres 行级权限保护不够：

- DB dump、备份、调试时都能直接读到明文 token；一次失泄就等于把所有用户 YouTube 频道交出去
- 单机 dev 环境（`.env` 自带的 demo 账号）和真账号（用户自己授权）都用同一张 `platform_credentials` 表，
  不能因为生产加密而让 dev 卡死
- token 在 adapter 真发时（`adapters/youtube.py::upload`）需要透明的 plain text，
  不能让加密层拖慢上传链路或污染 adapter 协议（`PublishRequest.credential` 仍是 `dict[str, Any]`）

要在「**安全**」「**dev 友好**」「**未来可 rotate**」之间做取舍。Track-01 已经选择 Fernet 落地，但当时没有写 ADR；
v1 工程闭环收口前需要把决策固化，避免后续轮替 KEY / 加平台时分歧。

## 候选方案

### 方案 A：KMS（AWS KMS / GCP KMS / Vault Transit）

- 优点：行业标准、KEY 自动轮换、HSM 级别物理隔离、审计日志
- 缺点：
  - 本地开发依赖太重（dev 启动要先 mock KMS endpoint，或者每个开发者拿一份 IAM 凭证）
  - 调用 KMS encrypt/decrypt 都是网络调用，发布链路上每条 token 解密 +50–200ms
  - 引入云厂商绑定；早期 self-host 用户没法直接 deploy
- 结论：v0 阶段不引入；M+（真上生产 + 多 tenant 真账号）时按 ADR-003 续作 ADR-XXX 评估迁移

### 方案 B：AES-GCM 自签 nonce

- 优点：纯 Python（`cryptography.hazmat.primitives.ciphers.aead.AESGCM`）、无运维负担、性能最好
- 缺点：
  - nonce 管理是常见 footgun（reuse → 灾难性密钥泄漏）；要自己设计 (key_id, nonce, counter) 协议
  - 自签格式没有版本号、TTL、KEY 标识，rotation 时必须自己加 metadata 字段
  - 没有现成的"密文格式可识别"能力 → 加密迁移脚本（`scripts/migrate_encrypt_creds.py`）没法用
    `_looks_encrypted` 这种 O(1) 幂等判断
- 结论：在 Fernet 已经覆盖 80% 需求时不值得 reinvent

### 方案 C：不加密（v0 状态）

- 优点：零工作量
- 缺点：DB dump = 全用户 token 泄漏；无法满足任何严肃 SLA / 合规要求
- 结论：上线前必须升级，本 ADR 即终结此方案

### 方案 D：单 Fernet KEY + 缺失静默降级（**选定**）

- 来源：Python `cryptography` 标准 `Fernet`（AES-128-CBC + HMAC-SHA256，url-safe base64 token，
  自带版本号 `\x80` + 时间戳 + IV，开箱即用）
- 行为：
  - 配 `PUBLISH_CREDENTIAL_FERNET_KEY` env → 落库前 `_encrypt(plain) → gAAAAA...`，
    读出时 `_decrypt(ciphertext) → plain`
  - 缺 KEY → `_get_fernet()` 返 None → 直接落 plain text + 模块级 `_WARNED_NO_KEY` 守卫只打一次
    `logger.warning`（不污染 publish 链路日志）
  - 老 plain text 行被读时 `Fernet.decrypt` 抛 `InvalidToken` → `_decrypt` 捕获后**原样返回**，
    迁移期 0 停机；想彻底升级再跑 `scripts/migrate_encrypt_creds.py`（幂等 + dry-run）
- 优点：
  - dev 零配置；新机器 clone 仓库 + `.env.example` cp 之后能跑全 publish 流程
  - 生产配 KEY 即得加密；KEY 不变时迁移可后台跑、不阻塞业务
  - 与现有 `cryptography` 依赖无新增（已被 JWT / OAuth 模块拉进来）
  - rotation 时 `MultiFernet([new_key, old_key])` 同时认两把 KEY，旧密文继续可读、新写入用新 KEY；
    可在线轮换无停机
- 缺点：
  - 单 KEY 泄漏 = 全部凭证泄漏（与 KMS 拿到 root credential 等价；可接受为早期取舍）
  - 缺 KEY 静默降级会让"以为加了"的部署反而裸奔；用启动日志 + ADR + Settings validator 三重提醒缓解

## 决策

**采用方案 D：单 Fernet KEY + 缺失静默降级**，作为 v1 凭证加密基线；KEY rotation 时升级到 `MultiFernet`。

KEY 来源：`Settings.publish_credential_fernet_key`，`.env` 字段
`PUBLISH_CREDENTIAL_FERNET_KEY`（见 `app/config.py::publish_credential_fernet_key` 第 129 行 +
`normalize_publish_credential_fernet_key` validator 第 131-138 行）。

实现细节：

- 加密 / 解密 /幂等检测：`app/services/publishing/credentials.py`
  - `_get_fernet()`（行 72-89）：惰性拿 `Fernet` 实例，KEY 缺失返 None，
    `_WARNED_NO_KEY` 模块级守卫只打一次 warning
  - `_encrypt(plain)`（行 92-101）：None / 空串原样返；无 KEY 时降级 plain text
  - `_decrypt(ciphertext)`（行 104-123）：`InvalidToken / ValueError` 捕获后原样返回，
    `logger.info` 一次（避免 publish 链路被 warning 刷屏）
  - `_looks_encrypted(token)`（行 126-137）：迁移脚本用的幂等判断
- DAO 路径：`upsert_credential` / `update_after_publish` / `_row_to_payload`
  统一在 DAO 层加解密，**所有调用方拿到的永远是 plain text**；adapter 协议（`PublishRequest.credential`）零感知
- 一次性升级：`scripts/migrate_encrypt_creds.py`
  - 幂等：`_looks_encrypted` 判定老行 → `_encrypt` → 写回，`already / upgraded / skipped / total` summary
  - `--dry-run` 仅打印；KEY 未配置时退出码 2（不会乱写明文）
  - 跑前置：`.env` 已配 KEY；可重复跑，新增的明文行下次跑会自然吸收
- adapter 解耦：`update_after_publish`（`credentials.py` 行 294-328）让 adapter 在内部 refresh
  token 后回写新 access_token，加密路径仍走 DAO，adapter 不接触 KEY
- 缺 KEY 兜底：模块首次访问 `_get_fernet()` 时打一次 `logger.warning` 引导
  「生产环境请尽快生成 KEY 并跑 scripts/migrate_encrypt_creds.py」

## 后果与权衡

| 维度 | 取舍 |
|---|---|
| dev onboarding | 零配置可启动，完整 publish 流程能跑（plain text 落库 + 启动 warning 提醒） |
| 生产部署 | `.env` 必须配 `PUBLISH_CREDENTIAL_FERNET_KEY`；缺失即裸奔（启动日志显式 warning） |
| 性能 | Fernet `encrypt / decrypt` 单次约 10–50µs；publish 链路上单次发布 <1ms 开销 |
| 迁移风险 | 老 plain text 行被解密时 graceful fallback，不阻塞业务；migrate 脚本幂等可重跑 |
| KEY 轮换 | 不停机：新 KEY 加到 `MultiFernet([new, old])` 列表头 → 新写入用新 KEY、老密文继续可解 → 老行 migrate 完毕后从列表里移除 old |
| KEY 泄漏 | 等价于全部 token 泄漏；建议生产用 `kms decrypt` 把 KEY 注入容器 env，不直接落 git |
| 合规审计 | DB dump 出来是密文；满足 SOC2 "数据静态加密" 基本要求；正式合规审计时再升级 KMS |

## 不做什么（明确边界）

- **不做** per-tenant KEY（v1 单 KEY 即可；多 tenant 不同 KEY 时 row level 加 `kms_key_id` 列再说）
- **不做** envelope encryption（DEK / KEK 分层）：现阶段 token volume 小，DEK 收益不显著
- **不做** 自动 KEY rotation 调度：rotation 是低频运维操作，写在 deployment runbook 即可
- **不做** 把整个 row 加密：只加密 `access_token / refresh_token`，其它列（`platform / scope / status`）保持明文便于 SQL 过滤 / debug

## 重新评估触发条件

满足任一即开 ADR-XXX 评估升级到 KMS / 多 KEY 方案：

1. 凭证表行数 > 100 万（KEY 单点风险开始接近合规 RTO 阈值）
2. 出现"用户要求自带 KEK"的企业版需求（合规客户、政府客户）
3. KEY 误泄事件发生 1 次（不分大小，必须复盘）
4. 多 region 部署，需要把 KEY 物理隔离到不同 region 的 KMS

## 引用

- 加密 / 解密：`app/services/publishing/credentials.py`（行 66-138 加密层 + 行 140-328 DAO）
- 配置项：`app/config.py::publish_credential_fernet_key`（行 124-138，含 `normalize_publish_credential_fernet_key` validator）
- 一次性升级脚本：`scripts/migrate_encrypt_creds.py`（行 36-119 入口 + 行 75-110 幂等核心）
- 上下游 ADR：ADR-001（工作流引擎）/ ADR-002（Agent 编排）/ ADR-004（多平台发布 SLA）
- 标准库：`cryptography.fernet.Fernet`（已在 requirements.txt） / `cryptography.fernet.MultiFernet`（rotation 时升级用）
