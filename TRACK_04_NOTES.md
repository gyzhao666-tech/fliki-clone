# Track-04 · ArtAgent v4 IP-Adapter 真接入 — 完成 NOTES

> 日期：2026-05-05  
> 分支：`track-04-art-ipadapter`  
> 依赖：v3 锚点参考板已生成（`outputs.character_anchor.url` 落库）

## 目标
把 v3 已生成的 `outputs.character_anchor.url` **真喂回** image provider 当 IP-Adapter
参考图，让每镜关键帧主角真正锁定（v3 仍是 prompt-only，跨镜会漂）。

## 改了哪些文件

### 1. `fliki-clone-api/app/services/model_gateway/providers/siliconflow_image.py`
- `RenderRequest.params` 新支持 `image_url` 透传。
- 增加 v4 IP-Adapter 真接入策略（详见文件 docstring）：
  - 若 env `SILICONFLOW_KOLORS_IP_MODEL` 配了官方上线后的 model id → 直接路由到该模型。
  - 否则用 `settings.image_model`（默认 Kwai-Kolors/Kolors），body 中同时塞
    `image` + `image_url` 两个常见 key 兼容多个后端模型。
  - **降级路径**：upstream 返 4xx 且响应体含
    `image_url` / `init_image` / `unsupported parameter` / `unknown parameter` /
    `invalid parameter: image` / `ip_adapter` / `reference image` 等关键词时，
    剥离 `image_url` 后**重试同一模型**一次（v4 → v3 prompt-only 兜底）。
- output 新增字段：`ip_adapter_used: bool` / 可选 `ip_adapter_degrade_reason: str`。
- 新增辅助函数 `_is_image_param_reject(body)`。

### 2. `fliki-clone-api/app/services/pipeline/agents/art.py`
- 模块 docstring 升级为 v3 / v4 双段，明确 IP-Adapter 策略。
- `_generate_keyframes` 签名新增 `character_anchor_url: str | None = None`。
- `ArtAgent.run` 调 `_generate_keyframes` 时把 `character_anchor.url` 透传过去。
- 行为：
  - `shot.character_locked == True` + anchor URL 存在 → 调用时传 `image_url`
  - 非主角镜 → 不传 `image_url`，避免污染聚焦角色脸
- 每镜 outputs 新增 `ip_adapter_used: bool`：默认 False，只有 provider 在 output
  里写 `True` 时才认为 IP-Adapter 真生效；并保留 `ip_adapter_degrade_reason`
  字段告诉前端「为什么没用上」。

### 3. `fliki-clone-api/app/services/model_gateway/types.py`
- 不改 dataclass schema；只在 `RenderRequest` docstring 里新增按 action 区分的
  `params` 常见键说明，重点写 `image_url` 在 GENERATE_IMAGE 下的语义 + 激活方式。

### 4. `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx::ArtArtifact`
- shots 网格 🔒 角标右侧加 v4「IP」二级徽标：
  - `character_locked && ip_adapter_used` → violet「IP」徽标（IP-Adapter ✓）
  - `character_locked && ip_adapter_degrade_reason && !ip_adapter_used`
    → amber「IP↓」徽标（hover title 显示 degrade reason）
  - 非 character_locked 镜不显示任何 v4 徽标
- 与 v3 「🔒」实现风格完全对称（同一外层 span，相同样式语言）。

## 严格遵守的边界（卡片要求）
- 没碰 `voice.py` / `video.py` / `publishing/` / `alembic/` / VoiceArtifact / VideoArtifact / PlanRow。
- 没改 schema，没加新表 —— `ip_adapter_used` 只走 `outputs_json`（与 v3 的
  `character_locked` 对称；不进 `shots` 表的列）。
- 没改 `app/config.py` / `.env`（Track-01 互斥锁），通过 env `SILICONFLOW_KOLORS_IP_MODEL`
  在 provider 内 `os.getenv(...)` 直读，不挂 settings。

## 烟测命令 + 结果

跨分支并行 agent 共用 `.env`（Track-01 已加 `PUBLISH_CREDENTIAL_FERNET_KEY`，但
本分支 `config.py` 还没该字段会 pydantic extra_forbidden）；本地烟测用临时脚本
mock `get_settings()` 绕过，结果如下：

| 用例 | 验证点 | 结果 |
| --- | --- | --- |
| case1_provider_strip_retry | provider 第一轮 422 unsupported parameter image_url → 第二轮剥离 image_url 重试同模型 → 200；`ip_adapter_used=false` + `degrade_reason` 写入 | PASS |
| case2_provider_ip_used | 第一轮 200，`ip_adapter_used=true`，`degrade_reason` 不写入 | PASS |
| case3_provider_no_image_url | 不传 image_url 时 body 里没 `image_url` 字段；`ip_adapter_used=false`，无 degrade | PASS |
| case4_agent_only_protag_gets_image_url | 主角镜（character_locked=True）调用带 image_url；非主角镜不带；只有主角镜 `ip_adapter_used=true` | PASS |
| case5_agent_no_anchor_no_image_url | anchor URL 为 None 时 → 主角镜也不传 image_url；ip_adapter_used 全程 false | PASS |
| case6_agent_provider_degrades | caller 传 anchor 但 provider 标 used=False 没标 degrade → agent 兜底写 「did not confirm」 | PASS |

合计 **6/6 PASS**。脚本跑完即删（不进 git，遵守 backlog 第 12 条）。

## SiliconFlow Kolors-IP 端点实测结果

**当前 SiliconFlow 公开 API（`/images/generations`）的 `Kwai-Kolors/Kolors` 模型
**不官方支持** `image` / `image_url` 字段作为 IP-Adapter 输入**。社区 fork（如
Kolors-IP-Adapter）需要走自部署路径，SF 暂未上线对应公开 model id。

本 Track 沙盒里**没有真打外网 SF 接口**（沙盒会注入 HTTP_PROXY 导致 403，且每次
keyframe ≈ $0.005 × N 镜真烧钱），结论靠（1）SiliconFlow 官方文档（`/v1/images/generations`
仅列 `model/prompt/image_size/batch_size/negative_prompt/seed/guidance_scale/num_inference_steps`，**无 image 参数**）+（2）provider 实现已设计成
「试着塞，不支持就剥离重试」的兼容策略。**实际激活路径**：

1. **当前 main 模型（Kolors / FLUX）**：v4 调用走通但 SF 多半返 422 unsupported
   → 自动剥离 image_url 重试 → 拿到一张 prompt-only 的图（≈ v3 行为）→
   `ip_adapter_used=false` + `ip_adapter_degrade_reason` 写入 → 前端显示 amber「IP↓」徽标。
   **没拿到真 IP-Adapter 锁定，但**：每镜的 `enhanced_prompt` 头部仍由 v3
   `[Consistent character: protagonist=...]` 注入了角色描述（v3 prompt-only
   兜底），跨镜一致性比 v2「主角随便漂」**仍有改善**，只是没达到 IP-Adapter 级别。
2. **将来 SF 官方上线 Kolors-IP / Flux Redux 公开端点**时：
   ```bash
   echo 'SILICONFLOW_KOLORS_IP_MODEL=Kwai-Kolors/Kolors-IP' >> fliki-clone-api/.env
   ```
   重启 backend → provider 自动路由到该模型 → 真 IP-Adapter 生效 → 主角脸跨镜
   像素级稳定 → 前端 violet「IP」徽标。

> 本 Track 已把 hook 全部留好：env 切一行就激活，**业务代码 / agent / 前端均无需改动**。

## 已知边界 / 跳过的子任务

- **没做真打外部 SF API 的烟测**（沙盒 HTTP_PROXY 403 + 真烧钱）；用 mock
  覆盖了 `requests.post` 全部分支。当用户自己有 `SILICONFLOW_API_KEY` 时，跑一遍
  pipeline `video_full`，根据后台日志可以看：
  - `art: keyframe failed for shot ...`：keyframe 报错 + `ip_adapter_degrade_reason` 写入
  - `SiliconFlow image model X rejected image_url (...); retrying without IP-Adapter`：
    剥离重试触发
  - shots 网格徽标会显示「IP↓」
- **没碰 `_persist_art`** —— 与 v3 的 `character_locked` 一样，`ip_adapter_used`
  只在 `outputs_json` 里。前端在 `useShotListSource=false` 路径下能直接读到；
  `useShotListSource=true` 时（shot_lists 表权威）这个字段不显示，与 v3 🔒
  徽标行为完全对称（v3 也只在 outputs_json 路径下显示）。如果未来要上 shot_lists
  表持久化，得先扩 `ShotOut` schema —— 这是 schema 层活，本 Track 不动。

## 后续 follow-up（建议给协调者）

1. **真接 Kolors-IP 端点（环境变量切换即可）**：等 SF 上线官方 IP-Adapter
   model id 后，`.env` 加一行 `SILICONFLOW_KOLORS_IP_MODEL=...`，重启 backend
   即可激活；不需要改业务代码。
2. **provider rate_limit 优化**：当前 v4 在 IP-Adapter 不支持时会**重试一次同模型**
   ——多花一次调用配额。在 keyframes 大量主角镜时累计可观；可以加
   `_known_image_param_reject_models: set[str]` 进程内 cache，命中后直接跳过 image_url
   不重试。等真有数据再优化。
3. **Track-09（多角色锁定）协议**：当 LLM 标 `focus_character != protagonist`
   且对应角色单独有 anchor URL 时，给该镜传该角色 anchor 而不是 protagonist anchor。
   现在 `_generate_keyframes` 已经预留了 character_anchor_url 单参数，多角色版需
   扩成 `anchors_by_role: dict[str, str]`，按 `focus_character` 选。
4. **shot_lists 表持久化** `ip_adapter_used`（依 Track-08 pytest 重构 + Track-04
   合并后做）：扩 `ShotOut` 加列 + `_persist_art` 写入。

## 提交

```
git commit -m "feat(art): v4 IP-Adapter 真接入；character_anchor.url 喂入 image provider"
git push origin track-04-art-ipadapter
```

注意：commit 时只 `git add` 我自己的 4 个文件 + 本 NOTES，**不**碰其他 agent
留在工作树的未提交改动（如 `.track02-worktree/` / `.track05-worktree/`、
其他 Track 的 `app/config.py` modifications 等）。
