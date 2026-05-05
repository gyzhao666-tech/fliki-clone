# ADR-005：ArtAgent 角色一致性 v3 → v4 → v5 → LoRA 演进路线

- 状态：Accepted
- 日期：2026-05-05
- 决策人：fliki-clone 团队
- 关联 Track：Track-04（v4 IP-Adapter 接入点）/ Track-05（VideoAgent v2 anchor 主参考帧）/
  Track-09（v5 多角色锁定）/ Track-10（canary feature flag 染色）/ Track-19 ⏸（v6 真 multi-IP，等外部依赖）
- 关联文档：`docs/adr/001-workflow-engine.md`、`docs/adr/002-agent-orchestration.md`、`SESSION_HANDOFF.md`

---

## 背景

ArtAgent v2（v1 第一版）每镜独立调一次 GENERATE_IMAGE 出关键帧。痛点：

- 主角脸 / 发型 / 服装跨镜漂；6 镜短视频里能出现 6 张"长得像但不是同一个人"的脸
- LLM 的 enhanced_prompt 只能描述"年轻女性、白衣、温和气质"这类**类别**特征，无法锁定**实例**
- VideoAgent 拿这些不一致的 keyframe 做 image-to-video，每段镜头主角看起来又不一样
- 用户主观感受："这视频换演员了？"，复看率塌方

要解决"跨镜锁定主角实例"问题，业界主流路线有三档：
1. **prompt 锁定**：把同一段角色描述前缀注入每镜 prompt（便宜，效果一般）
2. **IP-Adapter / image conditioning**：把一张参考图喂给 image provider，让模型按图锁脸（中等成本，效果好但单角色）
3. **LoRA fine-tune**：训一个角色专用的低秩适配权重（贵一次，推理便宜，多角色都稳）

v1 演进选择了 prompt → IP-Adapter（单角色） → IP-Adapter（多角色）三阶段，等外部多角色 IP 端点出来后接 v6，
LoRA 留远期。本 ADR 把每一阶段的实现位置 / 取舍 / 升级路径固化。

## 候选方案对比

| 方案 | 成本（每镜） | 锁定度 | 多角色 | 工程复杂度 | 外部依赖 |
|---|---|---|---|---|---|
| Prompt 注入（v3） | +0% | ★★☆☆☆ | 不锁配角 | 低（纯字符串拼接） | 无 |
| ControlNet pose lock | +1 次 ControlNet 推理 | ★★★☆☆（锁姿势不锁脸） | 不锁角色 | 中 | 需 ControlNet 节点 |
| IP-Adapter 单角色（v4） | +1 次 anchor 出图（一次性） | ★★★★☆ | 不锁配角 | 中 | 需 image provider 支持 image conditioning |
| IP-Adapter 多角色（v5） | +N 次 anchor（N=被 focus 的角色数） | ★★★★★ 多角色 | 锁主角 + 配角 | 中（v4 之上加角色选择） | 同 v4 |
| Multi-IP-Adapter（v6） | 同 v5 但单镜可同时锁多个角色 | ★★★★★ 同框多角色稳 | 同框多角色 | 中 | **等 SiliconFlow Kolors-IP / Replicate Flux Redux 真 multi-IP 端点上线** |
| 单角色 LoRA（远期） | 训练 ~$5–20 / 角色一次；推理 +0 | ★★★★★★ | 多角色（每角色一份 LoRA） | 高（训练 pipeline + 切换路由） | 需训练算力 + 1k+ 样本 |
| Dreambooth | 类似 LoRA 但显存更高 | ★★★★★★ | 同上 | 高 | 同 LoRA |
| 单角色 trained model 永久订阅 | 商业化阶段评估（成本结构不同） | ★★★★★★ | 单角色 | 低（接 SaaS） | 等成熟商业接口 |

## 决策

**采用渐进路线 v3 → v4 → v5（已落） → v6（等外部）→ LoRA（远期）**：

- 当前商业可用基线：**v5 多角色 anchor + Track-10 canary 染色**
- 等外部依赖：**v6 真 multi-IP**（外部端点上线即接，接入点已留）
- 远期路线：**LoRA 训练**（M+ 商业化阶段评估）

每个阶段的取舍 / 实现 / 升级路径见下。

### v3（已落）prompt-only：跨 provider 通吃的兜底

- **触发**：`brief.character_consistency ∈ ("auto", "prompt-only")` 且至少 1 张 character_card 存在
- **机制**：
  - `_inject_consistency_into_shots`（`agents/art.py` 行 636-708）按 `shot.focus_character` 选对应角色卡，
    用 `_build_character_prefix`（行 615-633）拼成
    `[Consistent character: protagonist=<name>; <appearance>; wardrobe=<wardrobe>; vibe=<vibe>] ` 前缀
  - 注入到每镜 `enhanced_prompt` 头部（最长 1200 字符截断）
  - `negative_prompt` 追加防漂关键词 `different face, different person, inconsistent character, multiple people`
    （`_CHAR_NEGATIVE_HINT` 行 149-151）
  - 每镜标 `character_locked: bool` + `locked_character: <name>` 让 VideoAgent / 前端可观察
- **成本**：+0%（同样 1 次 GENERATE_IMAGE / 镜，不多调）
- **锁定度**：★★☆☆☆ 主观看像同一个人但仔细比对仍漂；脸型 / 发际线 / 妆容容易换
- **优点**：所有 image provider 都生效，不依赖任何特殊端点
- **缺点**：模型仍按 prompt 描述生成，描述精确度有限；prompt token 预算被吃掉
- **降级路径**：v4/v5 anchor 全部失败时自动回到 v3（`agents/art.py` 行 271-295 anchor 全失败 → mode 降到 prompt-only）

### v4（已落）单角色 IP-Adapter：主角锁定基线

- **触发**：`brief.character_consistency ∈ ("auto", "anchor")` + 主角 anchor 出图成功 + image provider 支持 `image_url`
- **机制**：
  - `_generate_character_anchor`（行 562-612）单独调一次 GENERATE_IMAGE 出主角参考板（1:1 portrait, hero shot, neutral background）
  - URL 写入 `outputs.character_anchor.url` 后续 VideoAgent / 前端可复用
  - `_generate_keyframes`（行 390-506）在主角镜（`character_locked=True`）传 `params["image_url"] = anchor.url`
    给 image provider，走 IP-Adapter 路径
  - provider 不支持时（返 400 或 unknown parameter）`siliconflow_image.py` 自动**剥离 image_url 重试同模型**，
    本镜 `ip_adapter_used=false` + 写 `ip_adapter_degrade_reason`；不影响 keyframe 生成（v3 prompt-only 兜底依然生效）
- **成本**：+1 次 anchor 出图 ≈ $0.005 / 片（一次性，不分镜）
- **锁定度**：★★★★☆ 单主角脸 / 服装跨镜稳；配角不锁
- **激活方式**：env `SILICONFLOW_KOLORS_IP_MODEL=<官方上线后的 model id>`；缺省时仍尝试给现有 Kolors / FLUX 塞 image_url，
  由 provider 自决降级
- **outputs 兼容**：`outputs.character_anchor` 是主角 anchor（向后兼容前端 v3 徽标）；新增 `outputs.character_anchors` 字典留给 v5

### v5（已落）多角色 anchor + canary 染色：当前商业可用基线

- **触发**：v4 之上自动启用；`shot.focus_character != protagonist` 且该角色卡存在 → 该角色也出 anchor
- **机制**：
  - `_select_relevant_characters`（行 711-743）：主角始终保留 + 任何镜显式 focus 到的非主角角色
    （cards 顺序保持，前 4 个非主角；上限 5 防 estimate 爆炸）
  - `_generate_character_anchors`（行 746-776）批量出 anchor，返 `dict[name, anchor]`
  - `_inject_consistency_into_shots` v5 行为（行 660-708）：每镜按 `focus_character` 在
    `characters_by_name` 里找匹配卡（大小写不敏感），命中 → 注入**该角色的**前缀 + `locked_character=<name>`；
    未命中 → 不注入；缺省 focus → 默认主角
  - `_generate_keyframes`（行 390-506）按 `shot.locked_character` 在 `anchors_by_role` 里查对应角色 anchor URL，
    传 `image_url`；主角镜 → 主角 anchor、配角镜 → 配角 anchor
  - VideoAgent 复用：`agents/video.py::_select_ref_image`（行 264-294）按 `shot.locked_character` →
    `shot.focus_character` → `anchors_by_role` 第一个的优先级选 i2v 主参考帧
- **成本**：+N 次 anchor（N = 主角 + 真被 focus 的配角数；脚本只用主角时 N=1，与 v4 完全一致；
  3 角色脚本 N=3，约 $0.015 / 片）
- **锁定度**：★★★★★ 多角色脚本里每角色都锁；同框多角色仍依赖 provider 单图 multi-IP 能力（见 v6）
- **canary 染色**（Track-10）：
  - `art.py` 行 327-344 在 ArtAgent run 入口读 `ctx.feature_flags.get("art_ipadapter_pct")` →
    `pipeline_feature_flags.is_enabled(ctx.tenant_id, "art_ipadapter_pct", key=ctx.run_id, flags=ctx.feature_flags)`
  - 命中 → `anchors_url_by_role` 原样喂 `_generate_keyframes`（v4/v5 IP-Adapter）
  - 不命中 → 清空 `anchors_url_by_role`，所有镜降到 v3 prompt-only（character_anchor 前缀注入仍生效）
  - flag 缺省 → 默认走 v4/v5（向后兼容）
  - `feature_flags.is_enabled` 三种 value 形态：`{"enabled":bool}` / `{"pct":0..100}` / `{"variant":"v4"/"v3"}`
    （`feature_flags.py` 行 215-267）
  - outputs 写回 `canary_variant: "v4" / "v3-prompt-only"` + `canary_flag_value: <原 value>`，前端徽标可观察
- **outputs 兼容性**：`character_anchor`（主角，旧）+ `character_anchors`（dict，新）共存

### v6（外部依赖待启）真 multi-IP-Adapter：同框多角色稳

- **触发**：等 SiliconFlow Kolors-IP / Replicate Flux Redux 出 multi-IP 端点（一次推理同时 condition 多张参考图）
- **机制**：v5 的 `anchors_url_by_role` 字典已经按角色名组织好，v6 接入时把
  `params["image_url"] = single_url` 改成 `params["image_urls"] = list_by_role` 即可，**接入点已在 v5 留**
- **成本**：单镜推理调用次数不变；只多了"按角色名透传多 URL"的 wiring
- **锁定度**：★★★★★ 同框多角色每个都稳（v5 同框时仍只能锁 focus 角色）
- **当前阻塞**：外部端点未上线；Track-19 等待中
- **不做**：等不到外部端点期间不自己 stitch 多次 anchor（破坏一次推理一致性，且贵）

### 远期 LoRA 训练：商业化阶段路线

- **触发**：单 IP 商业化用户 / 角色 reuse 频率 > 10 次 / 月（按月预算评估 ROI）
- **机制**：
  - 训练数据集：anchor 出图迭代到 1k+ 高质量样本（用户上传 + 工程批量生成 + 人工挑选）
  - 训练成本：约 $5–20 / 角色一次，训练时长 30 min – 2h（按 GPU 与样本量）
  - 推理：与 v4 一样调一次 GENERATE_IMAGE，但 model 切到该角色专用 LoRA；推理成本同 base model（+0 边际成本）
  - 存储：`character_cards.lora_weight_url` 列（schema 待加；alembic 留 v1 加列槽 `e58c4a1d2b73` 之后）
  - inference 时按 `focus_character` 切 LoRA：`siliconflow_image.py` 加 `lora_url` param
- **锁定度**：★★★★★★ 训练充分时近乎完美；多角色脚本每个角色一份 LoRA 各自走自己的路径
- **成本结构**：训练贵一次（pre-pay）/ 推理便宜（vs IP-Adapter 每镜 +1 anchor cost）；
  适合「该角色会被反复用」的 IP 商业化场景
- **不替代 v5**：用户首次创建角色仍走 v5 anchor（即时可用、无训练等待）；用户主动决定"训成 LoRA"时升级
- **替代候选**：Dreambooth（同质方案、显存更高）/ 单角色 trained model 永久订阅（接 SaaS，成本结构与 LoRA 不同；商业化阶段评估）

## Tradeoff 总表

| 路线 | 一次性 cost | 边际 cost / 镜 | 多角色 | 同框多角色 | 训练数据需求 | 工程复杂度 | 何时启用 |
|---|---|---|---|---|---|---|---|
| v3 prompt-only | $0 | +$0 | 不锁 | 不锁 | 0 | 低 | 永远兜底 |
| v4 IP-Adapter 单 | $0.005（anchor） | +$0 | 不锁 | 不锁 | 0 | 中 | image provider 支持 image_url 时 |
| v5 IP-Adapter 多 | N×$0.005 | +$0 | ★★★★★ | ★★★（依赖 provider） | 0 | 中 | 当前默认（已落） |
| v6 multi-IP | 同 v5 | +$0 | ★★★★★ | ★★★★★ | 0 | 中 | 外部端点上线 |
| LoRA | $5–20 训练 / 角色 | +$0 | ★★★★★★ | ★★★★★★ | 1k+ 样本 / 角色 | 高 | 角色高频 reuse 时 |

## 后果与权衡

| 维度 | 取舍 |
|---|---|
| 成本控制 | 默认 v5；脚本只用主角时退化到 v4 成本（N=1 anchor）；canary 让单 tenant 内部分流验证 |
| Provider 可移植 | v3 prompt-only 永远生效兜底；image provider 切换不破坏 flow |
| 前端可观察 | outputs 含 `consistency_mode` / `character_anchor` / `character_anchors` / `canary_variant` / `canary_flag_value`，ArtArtifact 渲染 v3/v4/v5 徽标 + canary 实际命中档位 |
| VideoAgent 协同 | `_select_ref_image` 按 `locked_character` 选对应 anchor 作 i2v 主参考帧；多角色镜每镜走自己的 ref 图 |
| 失败兜底 | anchor 生成失败 → 单角色降到 prompt-only；prompt-only 仍生成 keyframe；keyframe 失败 → VideoAgent 降到 GENERATE_VIDEO（无 ref） |
| 升级路径 | v6：把 `params["image_url"]` 改 `params["image_urls"]` 即可；LoRA：加 schema 列 + 训练 pipeline + 推理路由切换 |
| 数据迁移 | character_cards 表已存在；LoRA 时加 `lora_weight_url` 列 + alembic |
| canary 风险 | flag 误配（pct=0）→ 全 tenant 退到 v3；outputs 留 `canary_flag_value` 可即时回查；admin UI（Track-14）可瞬时改回 |

## 不做什么（明确边界）

- **不做** ControlNet pose lock：锁姿势不锁脸，对"主角换演员"问题贡献小；增加 1 次推理 cost 不划算
- **不做** dreambooth：与 LoRA 同质但显存更高；选 LoRA 即跳过 dreambooth
- **不做** 强制把 v5 anchor 覆盖 v3 prompt：v3 prompt 注入是兜底，永远启用（即使 v5 全成功，prompt 也会注入；双层保险）
- **不做** v6 / LoRA 之间互斥：v6 上线后 LoRA 仍是高频 IP 角色的 ROI 路线；两条线并存
- **不做** anchor 缓存（同 tenant 同角色复用）：v1 每次 run 重新出 anchor；M+ 加 `character_cards.anchor_url` 列做缓存

## 重新评估触发条件

满足任一即开 ADR-XXX 评估：

1. SiliconFlow Kolors-IP / Replicate Flux Redux multi-IP 端点 GA → 启动 Track-19 接 v6（**本 ADR 续作**）
2. 单 tenant 月 anchor cost > $50（多角色脚本爆炸）→ 评估 anchor 缓存
3. 角色高频 reuse 用户 > 10 个（同一 IP 角色被用 > 10 次）→ 启动 LoRA 训练 pipeline 设计（新 ADR-006）
4. v3 prompt-only 投诉率 > 20%（用户主观感受"换演员了"）→ 把 v3 兜底从 default 改成 opt-in，全量 v5

## 引用

- ArtAgent v3/v4/v5 全在：`app/services/pipeline/agents/art.py`
  - SYSTEM_PROMPT（行 105-139）：character_cards 强制约定主角第一位
  - `_resolve_consistency_mode`（行 512-524）/ `_select_protagonist`（行 527-538）
  - v3 prompt 注入：`_inject_consistency_into_shots`（行 636-708）+ `_build_character_prefix`（行 615-633）
  - v3 锚点单角色：`_generate_character_anchor`（行 562-612）+ `_build_anchor_prompt`（行 541-559）
  - v5 多角色：`_select_relevant_characters`（行 711-743）+ `_generate_character_anchors`（行 746-776）
  - v4/v5 keyframe 注入 image_url：`_generate_keyframes`（行 390-506）
  - canary 染色：run 入口（行 327-344）+ outputs `canary_variant` / `canary_flag_value`（行 374-376）
- VideoAgent v5 协同：`app/services/pipeline/agents/video.py::_select_ref_image`
  （行 264-294 按 locked_character → focus_character → anchors_by_role 第一个优先级选 i2v ref-image）
- canary 基础设施：`app/services/pipeline/feature_flags.py`
  （`is_enabled` 行 215-267 三种 value 形态 / `_stable_bucket_0_99` 行 203-212 SHA-1 hash）
- 上下游 ADR：ADR-001（工作流引擎）/ ADR-002（Agent 编排）/ ADR-003（凭证加密）/ ADR-004（多平台发布 SLA）
- 历史 Track：Track-04 / Track-05 / Track-09 / Track-10 / Track-19（⏸ 等外部）
