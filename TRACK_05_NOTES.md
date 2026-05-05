# Track-05 · VideoAgent v2 — 用 character_anchor 作 i2v 主参考帧

> 分支：`track-05-video-anchor-ref`
> 范围：仅 `app/services/pipeline/agents/video.py` + `pipeline/page.tsx::VideoArtifact`
> 没有改 alembic / `.env` / art.py / publishing / 其他 panel；遵守 Track-04 / Track-08 互斥锁。

## 1. 改动摘要

### 后端 — `fliki-clone-api/app/services/pipeline/agents/video.py`

新增 ref-image 选择策略（v2）。逐镜按下面顺序挑：

| 优先级 | 条件 | 结果 | 备注 |
|---|---|---|---|
| 1 | `shot.character_locked === True` 且 `art.character_anchor.url` 存在 | `anchor` | 主角镜复用 ArtAgent v3 主角锚点参考板，跨镜稳定脸/服装；走 IMAGE_TO_VIDEO |
| 2 | `shot.keyframe_url` 存在 | `keyframe` | 非主角镜 / character_locked=False / focus_character 标了别人；走 IMAGE_TO_VIDEO |
| 3 | 以上都缺 | `none` | 降级 GENERATE_VIDEO，无 ref-image 一致性 |

每镜 `outputs.shots[i]` 新增字段：
- `ref_image_source: 'anchor' | 'keyframe' | 'none'` — 真正传给 gateway 的 ref 来源
- `ref_image_url: str | null` — 真正传的 URL（便于调试）

step 顶层 outputs 新增：
- `ref_image_summary: { anchor: int, keyframe: int, none: int }` — 一眼看 anchor 复用率
- `character_anchor_url: str | null` — 全局锚点 URL（即使每镜没用上也透出，供前端 / 后续 step 复用）

新增 helpers：
- `_character_anchor_url(ctx)` — 从 `ctx.upstream_outputs.art.character_anchor.url` 安全读取，trim 空白；缺失 / 空字符串 / None 一律返 None
- `_select_ref_image(*, shot, anchor_url, keyframe_url)` — 纯函数，返 `(url_or_none, source)`

### 前端 — `fliki-clone/src/app/.../pipeline/page.tsx::VideoArtifact`

- 加 `RefImageSource` 类型 + `<RefImageSourceBadge>` 组件：
  - **emerald「anchor 锚定」**：主角镜复用全片锚点参考板
  - **sky「keyframe」**：每镜独立关键帧
  - **muted「无参考」**：GENERATE_VIDEO 降级
- 每个 shot 卡片右上角绝对定位渲染徽标（`absolute right-1 top-1 z-10`）
- 头部摘要行新增 ref 来源汇总 chip（emerald N anchor · sky N keyframe · N none）
- `VideoShotView` 接口加 `ref_image_source`；`toViewFromShotList` 在 shot-list 路径下按 index 从 outputsShots lookup 取 `ref_image_source`（shot_lists 表暂不存这个列以避免新加 alembic 迁移；找不到时 fallback 到 keyframe_url 推断 → 准确值由后端 outputs_json 写入）
- 头部 chip 与每镜徽标共用同一份 sources 数组，UI 一致性强

## 2. 烟测命令 + 结果

跑了一份临时 mock-gateway 算法烟测脚本（**已删除**，遵守通用规则 12「不留 ad-hoc smoke 脚本」）：

```bash
cd fliki-clone-api && .venv/bin/python _smoke_track05.py  # 已删
```

覆盖的 case：

| # | 场景 | 期望 | 实际 |
|---|---|---|---|
| 1 | `_character_anchor_url` 各种形态（含 trim/缺失/空/None） | 5/5 | PASS |
| 2 | `_select_ref_image` 8 个 case（locked±anchor±keyframe 笛卡尔 + 空白 url 边界） | 8/8 | PASS |
| 3 | `VideoAgent.run()` 集成 mock gateway，5 镜混合（主角带 kf / 多角色带 kf / 主角无 kf / 非主角无 kf / 空 prompt） | sources=`['anchor','keyframe','anchor','none','none']`, summary=`{'anchor':2,'keyframe':1,'none':2}`, modes=`['image_to_video','image_to_video','image_to_video','generate_video']` | PASS |
| bonus | art.character_anchor.url 为空字符串 → 主角镜降级 keyframe + character_anchor_url 为 None | PASS | PASS |

也做了 import 检查（确保 syntax 通过）：

```bash
cd fliki-clone-api && DATABASE_URL_SYNC=postgresql://x@localhost/x .venv/bin/python -c \
  "from app.services.pipeline.agents.video import VideoAgent, _select_ref_image, _character_anchor_url"
# → import ok
```

前端 TypeScript / ESLint：

```bash
cd fliki-clone && npx tsc --noEmit -p .          # 0 errors
cd fliki-clone && npx eslint .../pipeline/page.tsx  # 0 errors（3 个 warning 是文件内既有未用变量，与本 Track 无关）
```

## 3. 不做 / 跳过

- **未跑真实 video_full 端到端**：sandbox 里跑 video step 会真打 Kling / SiliconFlow，1-2 min/镜 + $0.20/s 成本，且 SiliconFlow 在 sandbox 里会被 proxy 拦 403。算法层 5 镜混合 case 已通过 mock 验证。**用户合并后**在真机 macOS 重启 backend + 跑一次 `video_full` 验证：
  - shots 表每镜 `outputs_json.shots[i].ref_image_source` 落对
  - 主角镜应是 `anchor`，多角色镜应是 `keyframe`
  - 前端 video step 卡片右上角徽标颜色对应 emerald / sky / muted
  - 头部 chip 显示 anchor / keyframe 数量
- **不改 art.py**：Track-04 互斥锁；anchor URL 已经在 v3 落 `outputs.art.character_anchor.url`，本 Track 只读不写。
- **不改 schema / shot_lists 表**：alembic 互斥锁是 Track-02 专享；`ref_image_source` 字段只活在 `step.outputs_json.shots[i]` 里，前端 shot-list 路径用 outputs lookup 兜底取，无需新加列。
- **不改 video step 的 mode 含义**：`mode` 仍是 `image_to_video` / `generate_video`，与 ref_image 是否存在一致。`ref_image_source` 是更细粒度的辅助维度。
- **未在前端 `<ShotsSourceBadge>` / 其他 panel 上动手**：严格遵守「只改 VideoArtifact」的范围。

## 4. 后续 follow-up

- **alembic 加 `shots.ref_image_source` 列**（Track-02 互斥锁解锁后）：当前前端在 shot-list 路径下要从 outputs lookup 取 ref_image_source，多走一步；落库到 shots 表后可统一从 ShotOut 取，并支持按 source 筛选 / 历史比对。
- **Track-09 多角色锁定**（依赖 Track-04）：当 LLM 标了 focus_character != protagonist 时，给该角色单独出锚点；那时 `_character_anchor_url` 可以扩展到「按 focus_character 选不同 anchor」，本 Track 已经留好接口（每镜独立判断，只换 helper 实现）。
- **真接 IP-Adapter 后效果叠加**（Track-04 v4）：当 image provider 把 anchor 当作 IP-Adapter 输入时，主角镜的 keyframe 本身就跨镜稳定；本 Track 又把同一份 anchor 喂给 i2v 作首帧 → 期望主角脸/服装比 v1（每镜独立 keyframe）显著更稳。
- **i2v 模型对 anchor 1:1 aspect 的容忍度**：anchor 默认 1:1，但 video shot 可能是 9:16 / 16:9。Kling i2v 通常会按 prompt 的 aspect 重新构图，但极端情况下可能出现裁剪问题；如发现可在 `params` 里加上 `ref_image_aspect` 提示（provider 端尚未支持）。
- **`ref_image_url` 与 `keyframe_url` 同时落库时的去重**：v2 已经把 `ref_image_url` 单独写入 outputs；shots 表里仍是 `keyframe_url`（不变），但前端如果要显示「这镜真用了哪张图」可以读 `ref_image_url`（precise）而不是 keyframe_url（每镜独立的那张）。

## 5. 文件清单

- 改：`fliki-clone-api/app/services/pipeline/agents/video.py`
- 改：`fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx`（仅 `VideoArtifact` 函数 + 新增 `RefImageSourceBadge` + 类型/helper；不动其它 panel）
- 新增：本文件 `TRACK_05_NOTES.md`
