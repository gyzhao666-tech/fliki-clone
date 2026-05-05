# Fliki Clone — Python Backend API

FastAPI + PostgreSQL + Celery 后端，对接 [fliki-clone](../fliki-clone) 前端。

## 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI 0.115 |
| 异步 ORM | SQLAlchemy 2.0 (asyncpg) |
| 数据库迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 认证 | JWT (python-jose) + HttpOnly Cookie |
| 密码哈希 | passlib (bcrypt) |
| 异步任务 | Celery + Redis |
| 对象存储 | S3 兼容 (boto3) / Cloudflare R2 |
| 支付 | Stripe |
| AI | OpenAI GPT-4o-mini |
| TTS / 声音克隆 | ElevenLabs (可替换) |

---

## 快速启动

### 1. 准备环境

```bash
# 克隆后进入目录
cd fliki-clone-api

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填写 DATABASE_URL 和 JWT_SECRET
```

### 3. 启动 PostgreSQL（Docker）

```bash
docker run -d \
  --name fliki-postgres \
  -e POSTGRES_DB=fliki \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:16-alpine
```

### 4. 运行数据库迁移

```bash
make upgrade        # alembic upgrade head
make seed           # 写入演示数据（voices / templates / demo user）
```

### 5. 启动 Redis（Celery 依赖）

```bash
docker run -d --name fliki-redis -p 6379:6379 redis:7-alpine
```

### 6. 启动开发服务器

```bash
# 终端 1：API 服务
make dev            # uvicorn app.main:app --reload --port 8000

# 终端 2：Celery Worker（视频生成 / 导出任务）
make worker
```

### 7. 查看 API 文档

开发模式下（`DEBUG=true`）访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc:       http://localhost:8000/redoc

---

## 目录结构

```
fliki-clone-api/
├── app/
│   ├── main.py              # FastAPI 入口，注册所有路由
│   ├── config.py            # pydantic-settings 配置
│   ├── database.py          # 异步 SQLAlchemy engine + session
│   ├── deps.py              # JWT 鉴权依赖注入
│   ├── models/              # SQLAlchemy ORM 模型（16 张表）
│   ├── schemas/             # Pydantic v2 请求/响应 schema
│   ├── routers/             # 14 个功能模块路由
│   │   ├── auth.py          # P0 认证 + /me
│   │   ├── files.py         # P0 文件 / 文件夹 CRUD
│   │   ├── scenes.py        # P0/P1 场景编辑 + 视频生成 SSE
│   │   ├── exports.py       # P1 导出
│   │   ├── voices.py        # P1 声音库 / 克隆 / 自定义
│   │   ├── templates.py     # P1 模板
│   │   ├── assets.py        # P1 素材库
│   │   ├── characters.py    # P1 角色
│   │   ├── playground.py    # P3 图像生成
│   │   ├── brand_kits.py    # P2 品牌套件
│   │   ├── team.py          # P2 团队
│   │   ├── billing.py       # P2 Stripe 订阅
│   │   ├── rewards.py       # P2 积分 / 推荐
│   │   └── ai.py            # P3 AI 脚本 / 改写 / 翻译
│   └── utils/
│       ├── auth.py          # JWT 创建 / 验证
│       ├── storage.py       # S3 presigned URL
│       ├── email.py         # 邮件发送
│       └── tasks.py         # Celery 异步任务
├── alembic/                 # 数据库迁移脚本
├── scripts/
│   └── seed.py              # 演示数据种子
├── alembic.ini
├── requirements.txt
├── Makefile
└── .env.example
```

---

## 接口总览（60+ 个端点）

| 模块 | 端点数 | 优先级 |
|------|--------|--------|
| 认证 & /me | 9 | P0 |
| 文件 & 文件夹 | 12 | P0 |
| 场景编辑 & 视频生成 | 7 | P0/P1 |
| 导出 | 4 | P1 |
| 声音库 | 7 | P1 |
| 模板 | 2 | P1 |
| 素材库 | 3 | P1 |
| 角色 | 3 | P1 |
| Playground | 3 | P3 |
| 品牌套件 | 4 | P2 |
| 团队 | 4 | P2 |
| 订阅计费 | 4 | P2 |
| 积分 & 推荐 | 4 | P2 |
| AI 辅助 | 3 | P3 |
| **合计** | **69** | |

---

## 与前端对接

前端 Next.js 需配置反向代理（`next.config.ts`）将 `/api/*` 转发到后端：

```typescript
// next.config.ts
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};
export default nextConfig;
```

---

## 数据库迁移常用命令

```bash
# 根据 models/ 变更自动生成迁移文件
make migrate msg="add_xxx_column"

# 应用所有迁移
make upgrade

# 回滚一步
make downgrade
```

---

## 生产部署建议

```
API:      Railway / Render / Fly.io
数据库:   Supabase / Neon (PostgreSQL)
Redis:    Upstash Redis
存储:     Cloudflare R2（S3 兼容，免流量费）
```
