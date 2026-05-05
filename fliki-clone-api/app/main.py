from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import (
    admin_flags_router,
    cost_router,
    ai_router,
    assets_router,
    auth_router,
    billing_router,
    brand_kits_router,
    characters_router,
    dlq_router,
    exports_router,
    files_router,
    me_router,
    pipelines_router,
    playground_router,
    production_router,
    rewards_router,
    scenes_router,
    team_router,
    templates_router,
    voices_router,
)

settings = get_settings()


def _cors_allowed_origins() -> list[str]:
    """含 localhost 时同时放行 127.0.0.1，避免前端用不同主机名导致 SSE/EventSource 失败、进度一直 0%。生产请在 FRONTEND_URL 中只配置真实站点。"""
    from urllib.parse import urlparse

    primary = settings.frontend_url.strip()
    out = [primary]
    try:
        u = urlparse(primary)
        if u.hostname == "localhost" and u.port:
            out.append(f"http://127.0.0.1:{u.port}")
        elif u.hostname == "127.0.0.1" and u.port:
            out.append(f"http://localhost:{u.port}")
    except Exception:
        pass
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify DB connection
    from app.database import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if settings.debug:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "trace": traceback.format_exc()},
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ── Static files（本地开发，S3 未配置时存放合并视频）─────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "videos")
os.makedirs(_STATIC_DIR, exist_ok=True)
app.mount("/static/videos", StaticFiles(directory=_STATIC_DIR), name="static_videos")

# ── Register all routers under /api prefix ────────────────────────────────────
PREFIX = settings.api_prefix  # "/api"

# Auth & Me
app.include_router(auth_router, prefix=PREFIX)
app.include_router(me_router, prefix=PREFIX)

# Core content
app.include_router(files_router, prefix=PREFIX)
app.include_router(scenes_router, prefix=PREFIX)
app.include_router(exports_router, prefix=PREFIX)
app.include_router(templates_router, prefix=PREFIX)
app.include_router(voices_router, prefix=PREFIX)
app.include_router(assets_router, prefix=PREFIX)
app.include_router(characters_router, prefix=PREFIX)
app.include_router(playground_router, prefix=PREFIX)
app.include_router(brand_kits_router, prefix=PREFIX)

# Team & Account
app.include_router(team_router, prefix=PREFIX)
app.include_router(billing_router, prefix=PREFIX)
app.include_router(rewards_router, prefix=PREFIX)

# AI
app.include_router(ai_router, prefix=PREFIX)

# Pipelines (Agent 流水线) + 生产元数据 + 死信队列
app.include_router(pipelines_router, prefix=PREFIX)
app.include_router(production_router, prefix=PREFIX)
app.include_router(dlq_router, prefix=PREFIX)

# Admin · 灰度发布 / canary feature flags（Track-10）
app.include_router(admin_flags_router, prefix=PREFIX)

# Cost · 按 tenant 聚合的明细成本视图（Track-18）
app.include_router(cost_router, prefix=PREFIX)
