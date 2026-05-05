# Track-09 多角色锁定（v5）— 交接笔记

> 本 Track 在 ArtAgent v3/v4（只锁主角）+ VideoAgent v2（主角 anchor 作 i2v 主参考帧）的基础上，
> 把 anchor 升级为「每个 character_card 各一份」+ 按 `shot.focus_character` 逐镜选对应 anchor。
> 全部依赖 mock LLM 单测 + 集成测，无 DB / 无外网；6/6 全过 + 共存的 art_v3 8/8 也未被 break。

---

## 1. 改了哪些文件 + 为什么

### 1.1 `fliki-clone-api/app/services/pipeline/agents/art.py`

**新增 helper：**

- `_build_character_prefix(character)` —— 把任意角色卡的 appearance/wardrobe/vibe 拼成
  `[Consistent character: protagonist=Name; ...]` 前缀。从原 `_inject_consistency_into_shots`
  里抽出来复用，主角 / 配角共用同一段格式（前缀 key 名仍叫 `protagonist=` 是稳定格式，
  下游 LLM 训练数据风格统一；**语义上是「该镜画面焦点角色」**）。
- `_select_relevant_characters(character_cards, shots)` —— 从角色卡里挑出本片真正会被
  锁定的角色（含主角）。逻辑：主角永远保留；其余角色只有当至少一个 shot 显式标
  `focus_character` 命中其名字（大小写不敏感）时才纳入。脚本只用主角时返回 1 个，
  与 v3/v4 行为完全一致 —— **不浪费 image 调用**。
- `_generate_character_anchors(characters, ...)` —— 对 `_generate_character_anchor`
  的批量包装，返回 `({name: anchor_dict}, 累计成本)`。单个角色 anchor 失败仅记 error，
  不影响其它角色与后续流程。

**改造现有函数：**

- `_inject_consistency_into_shots`：新增 `characters_by_name` 可选参数。每镜按
  `focus_character` 在 `characters_by_name` 里查匹配卡（大小写不敏感）。命中 → 注入
  该角色前缀 + `character_locked=True` + 写新字段 `locked_character`；未命中（focus
  标了一个没角色卡的代号）→ `character_locked=False`（v3 兜底）；缺省 focus → 默认主角。
  **不传 characters_by_name 时退化为 v3 行为**（焦点不是主角的镜直接跳过）。
- `_generate_keyframes`：参数从 `character_anchor_url: str | None` 改成
  `anchors_by_role: dict[str, str] | None`。每镜按 `shot.locked_character` 在字典里
  查对应角色 anchor URL 作 `image_url` 喂给 image provider；缺失时本镜降到 prompt-only
  路径（不影响 keyframe 生成）。`locked_character` 缺失（旧数据）时兜底取第一个 anchor，
  保持 v4 行为。
- `ArtAgent.run`：把单角色 anchor 流程改成 `_select_relevant_characters` →
  `_generate_character_anchors`（**多张 anchor**）→ `_inject_consistency_into_shots`
  接 `characters_by_name`。outputs 新增 `character_anchors: dict[name -> anchor]`，
  **保留** `character_anchor` 单字段为主角的 anchor（v3/v4 旧消费方继续工作）。
- `estimate_cost_usd`：anchor 成本按 distinct `focus_character` 数量估（主角 1 张 +
  配角各 1 张，上限 5）。脚本只用主角时仍只算 1 张 —— v3 估算行为不变。

### 1.2 `fliki-clone-api/app/services/pipeline/agents/video.py`

**新增 helper：**

- `_character_anchors_by_role(ctx)` —— 替换原 `_character_anchor_url`。优先读
  `outputs.art.character_anchors`（v5 新字典），缺失时退到 `outputs.art.character_anchor`
  单 anchor 字段（v3 兼容）映射回 dict。返 `{name -> url}`。
- `_protagonist_name(ctx)` —— 从 `outputs.art.protagonist_name` 拿主角名（保留 v3 兼容
  字段 `outputs.character_anchor_url` 为主角的 URL）。

**改造现有函数：**

- `_select_ref_image`：签名改成接 `anchors_by_role: dict[str, str]`，返回元组多了第三项
  `anchor_role: str | None`（source=='anchor' 时返回该 anchor 对应的角色名；其它情况 None）。
  优先按 `shot.locked_character` 命中（v5），否则按 `shot.focus_character`，都没命中时
  兜底取第一个 anchor（v3 老 run 没 locked_character 字段时仍工作）。
- `VideoAgent.run`：用新 `anchors_by_role` 字典、改用新 `_select_ref_image` 元组解构、
  每镜结果加 `ref_anchor_role` 字段；outputs 新增 `ref_image_summary.by_role`（每角色
  anchor 被多少镜引用）+ `character_anchors_by_role` 字段（前端能列每角色 URL）。

### 1.3 `fliki-clone/src/app/.../pipeline/page.tsx`

**ArtArtifact：**

- 读 `out.character_anchors` 字典（v5）；存在且非空时优先渲染**多角色锚点 grid**（每角色一卡，
  主角 emerald 边框 + 「主角」标签，配角 violet 边框 + 「配角」标签，含失败态显示 ✕）；
  缺失时退回原 v3 单 anchor 渲染（保留向后兼容）。多角色时顶部加「v5 多角色」徽标。
- shots 网格：每镜读 `s.locked_character` + `s.focus_character`；非主角镜（locked_character
  != protagonist_name）的 🔒 角标变 violet 色 + 卡片底部加 violet 角色名标签；title
  里显示 `locked_character=...`，方便调试。

**VideoArtifact：**

- `VideoShotView` 新增 `ref_anchor_role: string | null` 字段，从 outputs 读 `ref_anchor_role`。
- 卡片头部摘要：anchor 镜按 role 统计，多角色时（`anchorRoles.length > 1`）追加 violet
  徽标「v5 · Hero×N / Villain×M」。
- 每镜卡片 shot 编号右侧加 emerald 角标显示 `ref_anchor_role`（仅 anchor 镜显示）。

### 1.4 `fliki-clone-api/tests/test_track09_multichar.py`（新文件）

6 个 case 覆盖 helper + 端到端：

| case | 类别 | 验证点 |
|---|---|---|
| `test_select_relevant_characters_picks_referenced` | unit | 3 张卡 + 2 张被 focus 引用 → 返 2 张含主角；不被 focus 的不出 anchor |
| `test_inject_consistency_picks_per_shot_character` | unit | 配角镜注入配角前缀（black suit，不含主角的 trench coat）；focus 没卡时不注入 |
| `test_art_run_multichar_creates_two_anchors` | unit | LLM 返 2 角色 → outputs.character_anchors 含 2 个；character_anchor 单字段=主角的；2 镜分别注入不同 prefix；keyframe 调用收到对应角色 anchor 作 image_url |
| `test_art_run_multichar_back_compat_single_card` | unit | 单角色卡 → character_anchors 只 1 个，character_anchor=该 anchor，所有镜锁主角 |
| `test_video_select_ref_image_per_character` | unit | _select_ref_image 按 locked_character / focus_character / 大小写不敏感 / 未命中兜底 |
| `test_video_agent_uses_correct_anchor_per_shot` | unit | VideoAgent.run 集成：2 角色 anchors，2 镜分别锁主/配角 → ref_image_source='anchor'，ref_anchor_role 各为对应名，gateway 收到对应 ref_image，summary.by_role 正确 |

---

## 2. 烟测命令 + 结果

```bash
cd /Users/zhaoguangyuan/project/empty-track09/fliki-clone-api && \
  /Users/zhaoguangyuan/project/empty/fliki-clone-api/.venv/bin/python -m pytest -v --tb=short
```

**结果：37 passed in 0.87s**

- Track-09 新增 6 个 case 全过
- 现有 31 个 case（art_v3 8 / publishing 8 / quota_v2 8 / voice_v4 7）零回归
- 关键 v3 行为兼容性测试 `test_inject_consistency_into_shots_skips_non_protagonist` 仍 PASS
  —— 证明 v5 没破坏单角色 / focus 没卡兜底路径

仅跑 Track-09：

```bash
.venv/bin/python -m pytest tests/test_track09_multichar.py -v
# 6 passed in 0.10s
```

---

## 3. outputs schema 变化（前端 / 调试方需要知道）

### 3.1 art step `outputs_json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `character_anchor` | dict \| null | **保留**（v3/v4 兼容）：始终是主角的 anchor。等于 `character_anchors[protagonist_name]` |
| `character_anchors` | dict[name, anchor_dict] \| null | **新增**（v5）：所有被锁定角色的 anchor 字典，至少含主角 |
| `protagonist_name` | str \| null | 保留（v3）：主角代号 |
| `consistency_mode` | str | 保留（v3）：`anchor` / `prompt-only` / `disabled` |
| `shots[i].character_locked` | bool | 保留（v3）：本镜是否注入了一致性 prompt |
| `shots[i].locked_character` | str \| undefined | **新增**（v5）：本镜被锁定的角色名（VideoAgent 据此选 anchor） |

### 3.2 video step `outputs_json`

| 字段 | 类型 | 说明 |
|---|---|---|
| `shots[i].ref_image_source` | "anchor" \| "keyframe" \| "none" | 保留（v2） |
| `shots[i].ref_image_url` | str \| null | 保留（v2） |
| `shots[i].ref_anchor_role` | str \| null | **新增**（v5）：source=='anchor' 时本镜真正用了哪个角色的 anchor |
| `ref_image_summary.by_role` | dict[name, count] | **新增**（v5）：每角色 anchor 被引用次数 |
| `character_anchors_by_role` | dict[name, url] \| null | **新增**（v5）：来自 art 上游的 anchor 字典快照 |
| `character_anchor_url` | str \| null | 保留（v2 兼容）：主角的 anchor URL |

---

## 4. 已知边界 / 设计取舍

1. **配角触发条件**：必须 LLM 在某个 shot 里显式标 `focus_character` = 配角名。如果 LLM
   没标但脚本里其实有配角戏，仍按主角处理。SYSTEM_PROMPT 里 `focus_character` 已有
   描述，依靠 LLM 判断；后续可加 brief 显式选项强制开启某角色 anchor。
2. **配角名拼写**：`focus_character` 必须能匹配上某个 `character_card.name`（大小写不
   敏感）。LLM 输出时若拼错会被当作未知角色 → 该镜 `character_locked=False` 退到普通
   keyframe。从测试覆盖看这条兜底是稳的。
3. **anchor 数量上限**：`estimate_cost_usd` 估配角上限 5；`_select_relevant_characters`
   实际不限。极端脚本 10 个不同 focus 角色会跑 10 张 anchor（≈$0.05），可控。
4. **`locked_character` 字段缺失兼容**：`_select_ref_image` 在 `character_locked=True`
   但 `locked_character` 字段缺失时（v3 老 run 已写库）兜底取 `anchors_by_role` 第一项，
   保持 v4 行为，避免老 run 重跑视频步骤报错。
5. **不动 alembic / publishing / config.py**：本 Track 完全不需要 schema 变更；新字段
   都装在已有 JSON 列（`outputs_json` / `meta_json`）里。
6. **不动 conftest.py**：`patch_gateway` fixture 只 patch art / voice 模块；video 模块
   单独 patch 在 `test_video_agent_uses_correct_anchor_per_shot` 里手动用 monkeypatch
   完成，避免跨 Track 互斥锁冲突。

---

## 5. 工作环境说明 — git worktree

实操中发现并行 agents 在同一 `/Users/zhaoguangyuan/project/empty` 目录里 `git checkout`
不同分支会互相冲掉对方的工作。我用 `git worktree add ../empty-track09 track-09-multi-character`
创建了独立 worktree，所有提交都来自这个 worktree。Track-09 的最终代码已 push 到
`origin/track-09-multi-character`，主目录不受影响（仍是其它并行 agent 在用）。

合并完后清理 worktree：

```bash
cd /Users/zhaoguangyuan/project/empty
git worktree remove ../empty-track09
```

---

## 6. 后续 follow-up

1. **真接入 IP-Adapter 多角色**：v4 接入点已经按角色 anchor 喂 `image_url`，但当前
   SiliconFlow Kolors 还不支持原生 multi-IP。等官方上线 multi-IP 模型后只需改
   `siliconflow_image.py`，agents 不动。
2. **brief.required_anchors**：可选 brief 字段强制为某角色出 anchor（即使 LLM 没标
   focus_character），适用于「主角 + 反派对手戏」剧本但 LLM 偶尔漏标的场景。
3. **EditAgent / 字幕高亮按 locked_character**：未来可按角色色板烧录不同字幕颜色
   （主角 emerald / 配角 violet），现在 `shots[i].locked_character` 已经写到 shot_lists
   表的 `meta_json` 里了，只需 EditAgent v6 读出来。
4. **前端：ProductionPanel 角色管理 UI**：让用户手动覆盖 `protagonist_role` /
   `focus_character` 重跑 art step。当前前端只能看不能改。
