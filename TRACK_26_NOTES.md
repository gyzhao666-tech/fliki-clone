# Track-26 · L-02 卡拉 OK 字幕高亮 — 交付 NOTES

- 分支：`track-26-karaoke-highlight`
- HEAD baseline：`292f4ff` (chore(coord): 修 make test 走 venv pytest + 派发第七波 5 Track)
- 完成时间：2026-05-05
- 工作量：≈ 半天（spec 估算一致）

## 1. 改了哪些文件 + 为什么

| 文件 | 类型 | 作用 |
|---|---|---|
| `fliki-clone/src/hooks/use-audio-current-word.ts` | **新增** | 卡拉 OK 高亮核心 hook：监听 `<audio>` 的 `timeupdate` / `seeked`，按 throttle ≤ 33ms (≈30fps) 在 v4 word-level subtitles 数组里二分查找当前 (subtitleIndex, wordIndex)。导出纯函数 `findCurrentWord(subtitles, currentTime)` 单独可测，hook 主体只负责挂监听 + 节流 + 把结果落到 `useState` |
| `fliki-clone/src/hooks/__tests__/use-audio-current-word.test.ts` | **新增** | `findCurrentWord` 单元测试（4 suite / 14 case）覆盖：空字幕 / null subtitles / 边界（前/后/NaN/Infinity）/ 命中第 N 条字幕 + 第 N 个 word / 字幕条间 gap 粘性 / 字幕无 words 数组 fallback / 正向单调推进 / seek 回退 / 单条字幕 / 空 words 数组 |
| `fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx` | **改动** | (1) 顶部 import 加 `useRef` + `useAudioCurrentWord` / `SubtitleWithWords` / `WordTimestamp`；(2) 把原本内联在 `StepArtifacts::if (step.agent_type === "voice")` 里的整段 voice 渲染抽出成独立 `VoiceArtifact` 组件（行号原约 1640-1883，现集中到新组件里），方便在组件顶部调 hook（hooks 不能在条件分支里调）；(3) `<audio>` 加 `ref={audioRef}` + `onPlay/onPause/onEnded` 控制 `isPlaying`；(4) 字幕 `<li>` wrapper 命中 `currentSubtitleIndex` 时整条加 `bg-sky-500/15 ring-1 ring-sky-400/40` + `transition-colors duration-150`；(5) word `<span>` 命中 `currentWordIndex` 时改色为 `border-violet-500 bg-violet-500 text-white shadow-sm` + `transition-colors duration-150`；(6) 顶部状态徽标加「卡拉 OK 实时高亮 ✓」（仅 `subtitle_granularity === "word"` 时显示）；(7) 字幕 `<details>` 在 word-level 场景默认展开，让用户一打开 voice 卡片就能看到高亮效果 |
| `TRACK_26_NOTES.md` | **新增** | 本文件 |

**互斥锁遵守情况**：

- ✅ 只动了 `pipeline/page.tsx::VoiceArtifact` 段（原内联的 voice 分支抽出），未触及 ArtArtifact / VideoArtifact / EditArtifact / PlanRow / ProductionPanel / DeadLetterPanel / 顶部段
- ✅ 新 hook 文件 + 新 test 文件均独占（`use-audio-current-word.ts` / `__tests__/`）
- ✅ 后端零改动（`fliki-clone-api/` 在我提交里完全没动）
- ✅ 没动 alembic / `.env.example` / `config.py`

## 2. 烟测命令 + 结果

### 2.1 单元测试（jiti 跑 node:test，14/14 PASS）

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone
node --import jiti/register --test src/hooks/__tests__/use-audio-current-word.test.ts
```

输出（节选）：

```
▶ findCurrentWord — 边界与无效输入
  ✔ 空字幕数组 → (-1, -1)
  ✔ subtitles 为 null → (-1, -1)（模拟 audio 为 null / 没字幕）
  ✔ currentTime < 第一条 start → (-1, -1)
  ✔ currentTime > 最后一条 end → (-1, -1)
  ✔ 非有限 currentTime（NaN / Infinity）→ (-1, -1)
✔ findCurrentWord — 边界与无效输入

▶ findCurrentWord — 命中点常规
  ✔ currentTime 正好 = 第一条 start → (0, 0)
  ✔ 第一条字幕中段 → (0, 中间 word)
  ✔ 第二条字幕 → (1, 对应 word)
  ✔ 第三条字幕（无 words 数组，v3 行级 fallback）→ (2, -1)
  ✔ 字幕条之间 gap → 粘到 SAMPLE[0] 末 word
✔ findCurrentWord — 命中点常规

▶ findCurrentWord — 单调推进（卡拉 OK 主线）
  ✔ audio.currentTime 从 0 → 7.5 推进 → (subIdx, wordIdx) 单调不回退
  ✔ seek 回退 → 函数纯返新位置
✔ findCurrentWord — 单调推进（卡拉 OK 主线）

▶ findCurrentWord — 单一字幕场景
  ✔ 单条字幕 + 单 word → 命中 (0, 0)；外面返 -1
  ✔ subtitle.words 为空数组 → (subIdx, -1)
✔ findCurrentWord — 单一字幕场景

ℹ tests 14
ℹ pass 14
ℹ fail 0
ℹ duration_ms 149.310458
```

### 2.2 TypeScript 编译

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone && npx tsc --noEmit
```

→ 无新增 error（baseline 干净）。

### 2.3 ESLint / 已知 lints

```bash
ReadLints on:
  - fliki-clone/src/hooks/use-audio-current-word.ts
  - fliki-clone/src/hooks/__tests__/use-audio-current-word.test.ts
  - fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx
```

→ No linter errors found。

### 2.4 后端 pytest baseline（未受影响）

```bash
cd /Users/zhaoguangyuan/project/empty/fliki-clone-api && \
  .venv/bin/python -m pytest \
    --ignore=tests/test_track27_rbac_role.py \
    --ignore=tests/test_track30_workspaces.py
```

→ `130 passed in 2.32s`（与 baseline 一致）。

> 注：跑 `make test` 时会看到 `144 passed, 2 failed`，2 失败发生在 `tests/test_track30_workspaces.py`（T-30 工作树残留的未完成 WIP，**不属于** Track-26 范围；见 §4 已知边界）。

### 2.5 手测（不强制 / 等部署）

浏览器拉一个 `subtitle_granularity === "word"` 的 voice run（需 `OPENAI_API_KEY` 走 Whisper-1 拿真 word timestamp），点 audio play 看：

- 当前字幕条整条 sky 背景 + 细环
- 当前 word span violet-500 实底 + 白字 + 阴影
- 顶部出现「卡拉 OK 实时高亮 ✓」徽标
- pause 时高亮粘在最后位置；resume 继续；seek 跳转命中目标 word

## 3. 设计决策

### 3.1 为什么把 voice 分支抽成独立 `VoiceArtifact` 组件？

原代码把 voice 渲染内联在 `StepArtifacts::if (step.agent_type === "voice")` 分支里。React hooks 不能在条件分支里调用（rules-of-hooks），而 `useAudioCurrentWord` / `useRef` / `useState` / `useMemo` 都需要在组件顶层。最干净的做法是抽一个新组件，让 hooks 只在 voice step 渲染时才挂载。这也跟 spec 用 "VoiceArtifact 段" 的命名约定对齐。

### 3.2 为什么用 `searchFloor`（≤ target 的最大下标）而非区间命中？

- VoiceAgent v4 的 `subtitle_alignment_quality === "word"` 走 ASR 真实 word timestamp，理论上每条 word 区间紧密相邻（end_i ≈ start_{i+1}），但 ASR 偶尔会留 ms 级间隙
- 直接区间命中（`start <= t <= end`）会在 gap 里返 -1，导致高亮闪烁（"今天" 高亮 → 0.05s 灰 → "天气" 高亮）
- 用 floor 语义粘到「最近一个 start ≤ 当前时间的 word」，gap 里继续高亮上一个 word，符合卡拉 OK 体感
- 真正的边界外（`t < first.start` / `t > last.end`）仍然返 (-1, -1)，让 UI 整体熄灭

### 3.3 throttle 33ms

浏览器 `timeupdate` 事件本身就是 ~250ms 一次，不会爆发。throttle 主要防 `seeked` / `seeking` 在用户拖进度条时连续触发导致 React state 抖动。33ms ≈ 30fps，比浏览器 timeupdate 频次更高一些，足以在 Whisper 单 word 平均 0.3-0.6s 的场景下平滑跟随。

### 3.4 `enabled = isPlaying` 而非 always-on

- audio paused 时不再触发 `timeupdate`，hook 内部 listener 也不会 tick（CPU 浪费有限），但 spec 要求 onPlay/onPause 控制 hook
- 实现上：paused 时 `enabled=false` → `useEffect` 早返 / 不 register listener，但 `useState` 保留上次位置（粘性）
- onPlay → `enabled=true` → listener register + 立即 `tick()` 同步当前 currentTime
- 这样 pause-resume 来回切不会闪烁到 (-1, -1)

### 3.5 hook 内部用 `subtitlesRef` 而不是 deps 数组里直接放 `subtitles`

`subtitles` 来自 `outputs_json`（每次 SSE step_state 推送都会 produce 新引用），如果直接进 `useEffect` deps，会反复 register/unregister listener，浪费 + 抖动。改成 ref 同步刷新 `subtitlesRef.current`，listener 闭包里读 `subtitlesRef.current` 拿最新值。

## 4. 已知边界 / 跳过的子任务（与 spec 对齐）

- **不做** autoplay：用户必须手动点 play 才开始高亮（spec 明确不做）
- **不做** 字幕条点击跳转 `audio.currentTime`：留给后续 polish（spec 明确不做）
- **不做** v3 行级 / v2 镜级字幕的高亮：那些字幕没有 word-level 时间戳，没法做 word 级卡拉 OK；目前对它们整条字幕仍会有 sky 背景命中（subtitleIndex 命中），但不会有 word 级 violet 高亮
- **`isWordLevel` 判定**：用 `out.subtitle_granularity === "word"` 而非「`subtitles` 里有任意条带 `words[]`」。原因：v3 / v2 退化场景下 subtitles 不会带 `words[]`，granularity 字段更可靠
- **TS 测试 runner**：项目无 jest/vitest 配置（spec 已说明）；用 `node --import jiti/register --test` 跑 node:test。jiti 已在 `node_modules/.bin/` 里（次依赖），不需新增 dev dep
- **手测未强制**：spec 写「手测（不强制）」；实际依赖 `.env` 配 `OPENAI_API_KEY` 才能跑出 word-level 字幕；本批由协调者真账号 e2e 时一并验证
- **工作树非 clean**：`git status` 在我提交完成后仍然会看到 T-27 / T-30 等其他 track 留下的 WIP（admin_flags.py / billing.py / pipelines.py / production.py / team.py / rbac.py 等）。**这不是 Track-26 的产物**——这些文件是其他并行 agent 在共享 worktree 里留下的未交付状态。我严格只 `git add` 自己的 3 个文件 + NOTES，未触碰其他 track 的工作

## 5. follow-up 建议

1. **L-02 后续 polish**（不进 v1）：
   - 字幕条点击跳转 `audio.currentTime`：在 `<li>` 加 onClick 设置 `audioRef.current.currentTime = subtitle.start`
   - autoplay：voice run 完成后自动播放（需用户首次交互后才允许，遵循浏览器 autoplay policy）
   - 字幕条滚动到当前位置：`currentSubtitleRef?.scrollIntoView({behavior: "smooth", block: "nearest"})`

2. **EditArtifact 也复用 hook**：v4 多比例字幕在 EditArtifact 也展示 subtitles，可以让烧录后的视频片段视频播放时联动高亮——但 EditArtifact 的 video 元素时间戳跟 voice audio 的 word timestamp 不一定对得上（视频可能循环或截切），要先确认 EditAgent 输出的 subtitles 是否仍带 word level（目前应该不带）

3. **测试基础设施**：v1 范围内 fliki-clone 没有 jest/vitest，跑 hook 测试需要 jiti loader。后续若引入 vitest 作为 dev dep，可把本测试文件保持兼容（`describe` / `it` / `expect` 三 API 都能从 vitest 导入），改 import 即可

4. **其他 voice 卡片配色 polish**：当前命中行用 `bg-sky-500/15 ring-1 ring-sky-400/40`，与 SubtitleStyleHint（sky 主题）有视觉冲撞；若 v2 觉得太重可考虑改 `bg-sky-500/10 ring-1 ring-sky-400/30`

## 6. 与本次提交相关的 git 状态

```bash
$ git log --oneline -2
<本提交 sha>  feat(track-26): 卡拉 OK 字幕高亮 — useAudioCurrentWord hook + VoiceArtifact 集成
292f4ff       chore(coord): 修 make test 走 venv pytest + 派发第七波 5 Track（T-26~T-30）

$ git diff --stat HEAD~1
 TRACK_26_NOTES.md                                                   |  ~140 ++++++
 fliki-clone/src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx | ~339+, ~241-
 fliki-clone/src/hooks/__tests__/use-audio-current-word.test.ts      |  ~210 ++++++
 fliki-clone/src/hooks/use-audio-current-word.ts                     |  ~150 +++++
 4 files changed
```

> 工作树（提交后）：3 个 Track-26 文件 staged + commit；其他被改/新增文件来自并行 agent，不属于本提交，由协调者后续合并各自分支处理。
