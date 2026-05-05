# fliki-clone（monorepo）

多 Agent 视频生产流水线：从 Brief → 选题 → 脚本 → 美术 → 配音 → 视频生成 → 拼接 → 质检 → 多平台发布。

## 结构

```
.
├── fliki-clone-api/       # FastAPI 后端（Python 3.10）
│   ├── app/
│   │   ├── routers/       # pipelines / production / dlq / scenes
│   │   ├── services/
│   │   │   ├── model_gateway/   # LLM/TTS/ASR/Image/Video provider 路由
│   │   │   ├── pipeline/        # runner + agents + quota v2 + DLQ
│   │   │   ├── publishing/      # 发布执行器 v1（dry-run/youtube/bilibili）
│   │   │   └── media/           # ffmpeg / 字幕 / 拼接
│   │   └── models/        # SQLAlchemy ORM（19 张表）
│   ├── alembic/           # 当前 head: 8b1f6c2d4a93
│   └── docs/adr/          # 架构决策记录（001 工作流 / 002 ADR-002 不引入 LangGraph）
├── fliki-clone/           # Next.js 16 前端（React Server + Webpack）
│   └── src/app/[locale]/(app)/app/project/[id]/pipeline/page.tsx  ← 主战场
├── DEVELOPMENT_PLAN.md    # 顶层路线图（13 节）
├── SESSION_HANDOFF.md     # 跨会话交接（项目当前能力 + 已知坑）
└── AGENTS_BACKLOG.md      # 多 Agent 并行 Backlog（8 个第一波 Track + 协调规则）
```

## 当前能力（截 2026-05-05 11:30）

完整跑通 video_full 端到端：
- **配额 v2** tenant 级分桶 + provider 并发桶（自动按 plan 派生 max）
- **VoiceAgent v4** word-level 强对齐（OpenAI Whisper / faster-whisper / SiliconFlow 三层 fallback）
- **ArtAgent v3** 角色一致性（锚点参考板 + prompt 锁定 + 防漂 negative）
- **EditAgent v5** 字幕按 aspect 重排（9:16 字号 44 / 16:9 字号 24，brief.subtitle_scale 整体缩放）
- **发布执行器 v1**（dry-run / youtube / bilibili adapter + executor + OAuth + DLQ 兜底）
- **数据模型扩展 v1**（9 张生产元数据表 + persist 双写 + `/api/production/*` 查询路由）
- **Celery 双模式**（CELERY_ENABLED 切；BackgroundTasks 兜底）+ **DLQ**（worker 异常持久化 + 前端 panel）
- **SSE 流式状态**（`GET /pipelines/{id}/events`；EventSource + polling fallback）

## 启动（dev）

**后端**：
```bash
cd fliki-clone-api
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填 SiliconFlow / Kling 等 key
alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

⚠️ **不要带 `--reload`**：本机 reload 会启 Python 3.12 子进程导致 `import app` 失败（venv 是 3.10）。

**前端**：
```bash
cd fliki-clone
npm install
npm run dev
```

打开 http://localhost:3000 → 登录 demo 账号 → 进任意 project 的 pipeline 页面。

## 多 Agent 协作

如果你以 Cursor Agent / 其他 AI Coding Agent 身份进入这个仓库，**第一件事 read [`AGENTS_BACKLOG.md`](./AGENTS_BACKLOG.md)**。

8 条 feature 分支已预创建（`track-01-credentials-fernet` … `track-08-pytest-suite`），每条对应一个独立任务，互斥锁已划清。

## 文档索引

| 文档 | 用途 |
|---|---|
| `DEVELOPMENT_PLAN.md` | 整体路线图，第 13 节是详细进展 |
| `SESSION_HANDOFF.md` | 项目当前能力 / 已知坑 / 配置约束（每个新会话开头必读）|
| `AGENTS_BACKLOG.md` | 多 Agent 并行 Backlog + 协调规则 + 长尾任务 |
| `fliki-clone-api/docs/adr/001-workflow-engine.md` | 工作流引擎选型 |
| `fliki-clone-api/docs/adr/002-agent-orchestration.md` | 不引入 LangChain/LangGraph 的论证 |

## License

未公开（personal project，prototype 阶段）
