# Track-28 · Celery worker Docker + docker-compose 单机部署 · NOTES

- **分支**：`track-28-celery-docker`
- **commit**：`e4a71f6 feat(track-28): Celery worker Docker + docker-compose 单机部署`
- **基线**：`292f4ff chore(coord): 修 make test 走 venv pytest + 派发第七波 5 Track`
- **范围**：纯 ops 工作；不动业务代码；不动 requirements / package.json

---

## 1. 改了哪些文件 + 为什么

| 文件 | 操作 | 行数 | 为什么 |
|---|---|---|---|
| `fliki-clone-api/Dockerfile` | 新增 | 49 | 单镜像 backend + worker；python:3.10-slim 与本机 venv 对齐；ffmpeg/libpq/gcc/curl；CMD uvicorn 不带 --reload |
| `fliki-clone/Dockerfile` | 新增 | 43 | Next.js 16 multi-stage；builder npm ci+build → runner npm start；不动 next.config.ts |
| `docker-compose.yml` | 新增 | 124 | 5 服务（postgres/redis/backend/worker/frontend）+ healthcheck + service_healthy 等待 |
| `.dockerignore` | 新增 | 52 | 仓库根文档备忘；docker build 实际不读它（只读 build context 根） |
| `fliki-clone-api/.dockerignore` | 新增 | 35 | backend build context 实际生效副本：忽略 .venv/__pycache__/.env/*.md |
| `fliki-clone/.dockerignore` | 新增 | 29 | frontend build context 实际生效副本：忽略 node_modules/.next/.env/*.md |
| `fliki-clone-api/Makefile` | 改（+15） | +15 | 末尾追加 docker-up/down/logs/rebuild target；不动既有 test / pipeline-worker |
| `docs/deployment.md` | 新增 | 241 | 单机 docker 部署完整指南：架构图 + 起步 + alembic + 验证 + 6 段排错 + follow-up |

合计 8 文件 / +588 行 / 0 删除（git stat 直接对应）。

---

## 2. 关键设计决定

### 2.1 backend / worker 共享同一 Dockerfile

少维护一份 Dockerfile，依赖一致；worker 在 docker-compose `command:` 覆盖默认 CMD：

```yaml
worker:
  command: ["celery", "-A", "app.services.pipeline.celery_app", "worker", "-Q", "interactive,media,default", "--concurrency=2", "--loglevel=info"]
```

与 `fliki-clone-api/Makefile::pipeline-worker` target 完全一致。生产想拆三个独立 worker（每队列独立资源池）只需复制 worker block 改 `-Q` 即可。

### 2.2 host .env 不用改，compose 内自动覆盖网络名

backend / worker 通过 `env_file: ./fliki-clone-api/.env` 读全部业务 key（SiliconFlow / Kling / OpenAI / Stripe / SMTP / Fernet）。compose 仅显式覆盖三组：

```yaml
DATABASE_URL_SYNC: postgresql://...@postgres:5432/...
DATABASE_URL: postgresql+asyncpg://...@postgres:5432/...
REDIS_URL: redis://redis:6379/0
CELERY_BROKER_URL: redis://redis:6379/0
CELERY_RESULT_BACKEND: redis://redis:6379/1
CELERY_ENABLED: "true"
```

这样 host 上的 `.env` 仍写 `localhost:5432` / `127.0.0.1` 不变，host 直跑 uvicorn 也能用，docker 网络里自动指向 service 名，互不打扰。新机器部署只需 `cp .env.example .env` 填 SILICONFLOW_API_KEY / KLING_* 等业务 key 即可。

### 2.3 frontend 用 host 视角的 NEXT_PUBLIC_API_URL

```yaml
NEXT_PUBLIC_API_URL: http://localhost:8000
```

不是 `http://backend:8000`。因为 NEXT_PUBLIC_* 会被打到浏览器 bundle 里，浏览器跑在用户的 host 上，不是容器网络里 —— 必须用 host 视角的 `localhost:8000`。

### 2.4 healthcheck + condition: service_healthy 解决启动顺序

backend lifespan 里跑 `SELECT 1` 验证 PG 连接；如果 PG 还没 ready 直接抛 503 反复 restart。三个 healthcheck：

- `postgres`: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`
- `redis`: `redis-cli ping`
- `backend`: `curl -fsS http://localhost:8000/health`（main.py 第 103 行有 `/health` 端点，返 `{"status":"ok"}`）

backend depends_on `postgres + redis service_healthy`；worker depends_on `backend + redis service_healthy`；frontend depends_on `backend service_healthy`。

### 2.5 .dockerignore 三副本

docker build 默认只读 build context 根的 `.dockerignore`。本仓库 build context 是 `./fliki-clone-api` 和 `./fliki-clone`，所以仓库根的 `.dockerignore` 实际不生效（per Docker 文档）。但 spec 明确要求"新 .dockerignore（仓库根）"，我创建了三份：

- 仓库根 `.dockerignore`：文档备忘 + 防止后续 someone 把 build context 升到仓库根重新踩坑
- `fliki-clone-api/.dockerignore`：实际生效，忽略 .venv / __pycache__ / .env / *.md
- `fliki-clone/.dockerignore`：实际生效，忽略 node_modules / .next / .env / *.md

---

## 3. 烟测结果

### 3.1 yaml 合法性（python yaml）

```bash
$ python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"
# OK，无异常
```

深度结构检查：

```
services: ['backend', 'frontend', 'postgres', 'redis', 'worker']
volumes: ['postgres_data']
worker.command: ['celery', '-A', 'app.services.pipeline.celery_app', 'worker', '-Q', 'interactive,media,default', '--concurrency=2', '--loglevel=info']
backend.depends_on: {'postgres': {'condition': 'service_healthy'}, 'redis': {'condition': 'service_healthy'}}
frontend.environment.NEXT_PUBLIC_API_URL: http://localhost:8000

  postgres: OK
  redis: OK
  backend: OK
  worker: OK
  frontend: OK
depends_on healthy 全部 OK
  env_file backend: ./fliki-clone-api/.env → EXISTS
  env_file worker: ./fliki-clone-api/.env → EXISTS
  build backend: ./fliki-clone-api/Dockerfile → EXISTS
  build worker: ./fliki-clone-api/Dockerfile → EXISTS
  build frontend: ./fliki-clone/Dockerfile → EXISTS
  worker.command joined: celery -A app.services.pipeline.celery_app worker -Q interactive,media,default --concurrency=2 --loglevel=info
```

### 3.2 docker compose config 验证

**本机没装 docker compose v2 plugin**（只装了 docker v1 CLI），下面命令都失败：

```bash
$ docker compose config 2>&1
docker: 'compose' is not a docker command.

$ which docker-compose
docker-compose not found
```

→ 留给协调者环境验证 `docker compose config`。yaml 合法性已用 python yaml.safe_load 充分验证（结构 + 字段 + 路径 + 命令拆分均 OK，见 3.1）。

### 3.3 既有 pytest 130 case 不动

```bash
$ cd fliki-clone-api && make test 2>&1 | tail -3
============================= 130 passed in 2.57s ==============================
```

✅ 130/130 PASS（未引入业务代码改动）。

### 3.4 docker compose build 没跑

本机没 docker compose v2 + docker daemon 没起（`docker info` 报 daemon not running），无法跑 `docker compose build`。Dockerfile 语法本身没办法离线 lint（hadolint 也没装）。留给协调者：

```bash
docker compose build 2>&1 | tail -20
docker compose up -d
docker compose ps   # 等所有 service 变 healthy
docker compose exec backend alembic upgrade head
curl -fsS http://localhost:8000/health
open http://localhost:3000
```

---

## 4. 已知限制 / 边界

- **本机无 docker compose v2，未跑 `docker compose config` / `docker compose build`**：
  yaml 合法性靠 python yaml.safe_load + 字段结构检查，build syntax 留给协调者。
- **macOS docker volume 性能**：本 compose 没 host bind mount（只 named volume `postgres_data`），不会触发 macOS osxfs 慢的问题。如果要把代码 hot-reload mount 进容器开发，自加 `volumes: - ./fliki-clone-api/app:/app/app:cached`（cached 比 consistent 在 macOS 快）。
- **SSL cert 透传**：本 Track 没配 TLS；本地用纯 HTTP；生产前面套 nginx / caddy 做 TLS 终止。
- **.env 必须手 cp**：spec 要求 `cp fliki-clone-api/.env.example fliki-clone-api/.env` 才能跑 docker compose（env_file 找不到文件会报错）。`.env.example` 仅含 STRIPE/SMTP/ADMIN_EMAILS 段；SiliconFlow / Kling / DATABASE_URL 等没在 example 里，需要从 SESSION_HANDOFF.md 第 9 节复制；docs/deployment.md 已说明。
- **alembic upgrade 不自动跑**：backend lifespan 只跑 `SELECT 1`，不自动 alembic upgrade（避免多副本 race）。首次起或合 schema 改动后必须手动 `docker compose exec backend alembic upgrade head`，docs 已说明。
- **secrets 用 env_file 直接 mount**：dev 友好；生产用 docker secret / k8s secret / vault 注入。
- **前端环境变量打进 bundle**：`NEXT_PUBLIC_API_URL` 在 `next build` 时被烧进 client bundle；改 API 端口需要 `docker compose build --no-cache frontend` 重新打包。docs 已说明 docker-rebuild target。
- **同环境多并行 Track**：本工作目录同时被 T-26 / T-27 / T-29 / T-30 修改（其它 router / page.tsx / hook 等文件 untracked 或 modified，与本 Track 无关）；本 commit **仅显式 add Track-28 的 8 个文件**，不走 `git add -A`，避免把其他 Track 工作误并入本 commit。`git status` 不 clean 是因为其它 Track 还在跑，**不是 Track-28 漏 commit**。

---

## 5. Follow-up（建议后续 Track 接）

| ID | 内容 | 工作量 |
|---|---|---|
| L-06.1 | k8s helm chart：5 个 service 转 Deployment + Service + ConfigMap + Secret，PG 单独 PVC | 1.5-2 天 |
| L-06.2 | GitHub Actions：每 push 跑 `docker compose build` + push 到 ghcr.io / dockerhub | 半天 |
| L-06.3 | nginx / caddy 前置反代 + TLS 终止 + rate limit | 半天 |
| L-06.4 | postgres backup：cron `pg_dump` + S3 上传 + retention 30 天 | 半天 |
| L-06.5 | celery worker 拆三个独立进程（每队列一个，各自 concurrency 调优） | 1-2 小时 |
| L-06.6 | SSL cert 透传：环境里有 corp CA cert 时让 backend / worker 装到 `/etc/ssl/certs/` | 1-2 小时（按需） |

---

## 6. 协调者合并步骤建议（参考）

```bash
git checkout main
# 看本 NOTES → 协调者环境（带 docker compose v2）跑：
cd /Users/zhaoguangyuan/project/empty
docker compose config 2>&1 | head -50          # yaml 必须合法
docker compose build 2>&1 | tail -20            # 完整 build syntax 验证
# 可选：真起一遍
docker compose up -d
docker compose ps                                # 等 healthy
docker compose exec backend alembic upgrade head
curl -fsS http://localhost:8000/health
docker compose down

# 合并
git merge --no-ff track-28-celery-docker
git branch -d track-28-celery-docker
rm TRACK_28_NOTES.md           # 合到 SESSION_HANDOFF.md
# 更新 SESSION_HANDOFF.md：在第七波合并表里加 T-28 / 在第 9 节本机配置约束加"docker compose 部署 → 见 docs/deployment.md"
```
