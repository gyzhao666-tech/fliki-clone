# 单机 Docker 部署指南（Track-28）

> 适用：本机 / 单台 VPS 跑一份完整 fliki-clone。生产多节点 / k8s 不在本指南范围。

---

## 0. 架构

```
┌────────────┐   ┌──────────────┐   ┌──────────────┐
│ frontend   │──▶│   backend    │──▶│  postgres    │
│ Next.js 16 │   │  FastAPI +   │   │   15-alpine  │
│  :3000     │   │  uvicorn     │   └──────────────┘
└────────────┘   │  :8000       │   ┌──────────────┐
                 │              │──▶│   redis      │
                 └──────┬───────┘   │  7-alpine    │
                        │           └──────┬───────┘
                        │ celery dispatch  │
                        ▼                  │
                 ┌──────────────┐          │
                 │   worker     │──────────┘
                 │  celery -Q   │
                 │  i / m / d   │
                 └──────────────┘
```

5 个 compose 服务，命名空间在仓库根 `docker-compose.yml`：

| service | 镜像 | 暴露端口 | 关键作用 |
|---|---|---|---|
| `postgres` | `postgres:15-alpine` | （仅 compose 网络） | 主数据库；`postgres_data` named volume 持久化 |
| `redis` | `redis:7-alpine` | （仅 compose 网络） | celery broker + result backend + SSE redis Stream + quota / provider bucket |
| `backend` | 本地 build `fliki-clone-api/` | `:8000` | FastAPI；alembic 迁移要进容器手动跑 |
| `worker` | 同 backend 镜像 | （无）| celery 三队列单进程：`-Q interactive,media,default --concurrency=2` |
| `frontend` | 本地 build `fliki-clone/` | `:3000` | Next.js 16 production server (`next start`) |

---

## 1. 前置准备

### 1.1 安装 Docker

- macOS：装 [Docker Desktop](https://www.docker.com/products/docker-desktop)（自带 `docker compose v2`）
- Linux：装 `docker-ce` + `docker-compose-plugin`（apt / yum 都有）
- 验证：

```bash
docker --version          # >= 24.x
docker compose version    # >= v2.20.x（带 healthcheck condition: service_healthy 语法）
```

### 1.2 配 `.env`

backend / worker 从 `fliki-clone-api/.env` 读全部业务 key。**容器里**的 `DATABASE_URL_SYNC` /
`REDIS_URL` 由 `docker-compose.yml` 强制覆盖走 compose 网络服务名（`postgres:5432` / `redis:6379`），
所以 `.env` 里写 `localhost:5432` 都没关系（host 直跑 uvicorn 也能用，互不打扰）。

最小可起步 `.env`（在 `fliki-clone-api/` 下）：

```bash
cd fliki-clone-api
cp .env.example .env

# 关键 key（按需填）：
#   SILICONFLOW_API_KEY=sk-...    （video_full pipeline 几乎所有 step 都要）
#   KLING_ACCESS_KEY=AQ...        （视频生成；不配走 SiliconFlow Wan）
#   KLING_SECRET_KEY=Gm...
#   OPENAI_API_KEY=sk-...         （可选：voice v4 word-level + ASR 路由）
#   STRIPE_SECRET_KEY=sk_test_... （可选：billing）
#   STRIPE_WEBHOOK_SECRET=whsec_...
#   PUBLISH_CREDENTIAL_FERNET_KEY=...  （可选：YouTube/平台凭证加密）
#   ADMIN_EMAILS=demo@example.com,you@example.com
#
# DATABASE_URL_SYNC / REDIS_URL / CELERY_* —— 不用改，compose 会覆盖
```

可选：在仓库根新建 `.env` 覆盖 PG 默认账号（compose 默认 `fliki / fliki / fliki`）：

```bash
# /Users/zhaoguangyuan/project/empty/.env （仓库根）
POSTGRES_USER=fliki
POSTGRES_PASSWORD=fliki
POSTGRES_DB=fliki
```

---

## 2. 起步

```bash
cd /Users/zhaoguangyuan/project/empty   # 仓库根

# 一键起 5 个服务（首次会 build；约 5-10 分钟取决于网络）
docker compose up -d

# 看健康状态：postgres / redis / backend 都应该最终变成 healthy
docker compose ps

# 看日志（Ctrl+C 退出，容器仍在跑）
docker compose logs -f --tail=100
```

也可以从 `fliki-clone-api/` 用 `make` 包装：

```bash
cd fliki-clone-api
make docker-up        # docker compose up -d
make docker-logs      # docker compose logs -f --tail=100
make docker-down      # docker compose down
make docker-rebuild   # docker compose build --no-cache（改了 requirements.txt / Dockerfile 时用）
```

---

## 3. 跑 alembic 迁移（首次 / schema 改动）

backend lifespan 启动时只跑 `SELECT 1`，**不会自动 alembic upgrade**（避免多副本 race）。
首次起来或合 schema 改动时手动进 backend 容器跑：

```bash
docker compose exec backend alembic upgrade head
# 期望：head = d4e5f6a7b8c9（含 team_members.role；与 host venv 走的 head 一致）
```

降级：

```bash
docker compose exec backend alembic downgrade -1
```

---

## 4. 验证

```bash
# 4.1 backend health
curl -fsS http://localhost:8000/health
# → {"status":"ok","version":"1.0.0"}

# 4.2 路由数
docker compose exec backend python -c "from app.main import app; print(len(app.routes))"
# → 125+ （含 admin_flags / cost / billing / dlq / pipelines / production / team / RBAC ...）

# 4.3 alembic head
docker compose exec backend alembic current
# → d4e5f6a7b8c9 (head)

# 4.4 前端
open http://localhost:3000
# 浏览器看到登录页 → 注册 demo@example.com → 进 /app/project 新建 → 跑 video_full pipeline

# 4.5 worker 收 task
docker compose logs worker --tail=50
# → 起步时打 "celery@... ready." + "Connected to redis://redis:6379/0"
```

---

## 5. 常见排错

### 5.1 backend 反复 restart，日志里 `connection refused`

PG / redis 没 ready，但 backend 已经起了。

排查：

```bash
docker compose ps     # 看 postgres / redis 是否 healthy
docker compose logs postgres --tail=50
```

healthcheck 已经在 compose 里配了 `condition: service_healthy`，理论上不应该出现。
如果出现，用 `docker compose down -v && docker compose up -d`（删 volume 重新初始化 PG）。

### 5.2 alembic upgrade 抛 `psycopg2.OperationalError: could not connect`

容器里跑 alembic 时 `DATABASE_URL_SYNC` 应被 compose 覆盖成 `postgres:5432`；
确认走的是 `docker compose exec backend alembic ...` 而不是 host 上的 `alembic ...`：

```bash
docker compose exec backend env | grep DATABASE_URL_SYNC
# → DATABASE_URL_SYNC=postgresql://fliki:fliki@postgres:5432/fliki
```

### 5.3 redis connection refused / celery worker 起不来

```bash
docker compose exec redis redis-cli ping
# → PONG

docker compose exec worker env | grep CELERY_BROKER_URL
# → CELERY_BROKER_URL=redis://redis:6379/0
```

### 5.4 OAuth callback URL 不对

YouTube / Google / GitHub OAuth 在 Google Cloud Console 配 callback 时，
本机 docker 部署用 `http://localhost:8000/api/auth/...` 即可（前端浏览器和后端
端口都暴露在 host 上）。如果暴露到公网，记得把 callback 改成真域名。

### 5.5 SiliconFlow / Kling / OpenAI 被代理拦 403

容器里 `HTTP_PROXY` / `HTTPS_PROXY` 一般不会被 inherit；如果是公司网络要走代理：

```yaml
# docker-compose.override.yml （不进 git，自定义）
services:
  backend:
    environment:
      HTTP_PROXY: http://host.docker.internal:7890
      HTTPS_PROXY: http://host.docker.internal:7890
      NO_PROXY: postgres,redis,localhost,127.0.0.1
  worker:
    environment:
      HTTP_PROXY: http://host.docker.internal:7890
      HTTPS_PROXY: http://host.docker.internal:7890
      NO_PROXY: postgres,redis,localhost,127.0.0.1
```

### 5.6 macOS 文件 mount / volume 性能慢

本 compose 没 host bind mount（只用 named volume `postgres_data`），不会触发 macOS
osxfs 慢的问题。如果要把代码 hot-reload mount 进容器开发，再加：

```yaml
backend:
  volumes:
    - ./fliki-clone-api/app:/app/app:cached     # cached 比 consistent 在 macOS 快很多
```

---

## 6. 已知限制 / Follow-up

- **生产部署**：本指南是单机 docker compose；多节点请走 k8s（helm chart 待写，见 AGENTS_BACKLOG follow-up）
- **secrets**：`.env` 直接 mount 进容器（dev 友好）；生产用 docker secret / k8s secret / vault 注入
- **CI 镜像 push**：本 Track 不含 GitHub Actions build & push registry workflow；上线前补
- **多 worker 拆队列**：默认单 worker 进程跑三队列；想拆三个独立 worker（每队列独立资源池），
  复制 `worker` block 改 `-Q interactive` / `-Q media` / `-Q default` + 不同 service 名即可
- **postgres data 持久化**：仅 named volume；生产要做 backup / streaming replication 另外配
- **TLS / 反代**：本指南只暴露 :3000 / :8000；生产前面套 nginx / caddy 做 TLS 终止
