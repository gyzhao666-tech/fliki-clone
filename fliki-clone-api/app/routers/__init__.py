from app.routers.auth import router as auth_router, me_router
from app.routers.files import router as files_router
from app.routers.scenes import router as scenes_router
from app.routers.exports import router as exports_router
from app.routers.voices import router as voices_router
from app.routers.templates import router as templates_router
from app.routers.assets import router as assets_router
from app.routers.characters import router as characters_router
from app.routers.playground import router as playground_router
from app.routers.brand_kits import router as brand_kits_router
from app.routers.team import router as team_router
from app.routers.billing import router as billing_router
from app.routers.rewards import router as rewards_router
from app.routers.ai import router as ai_router
from app.routers.dlq import router as dlq_router
from app.routers.pipelines import router as pipelines_router
from app.routers.production import router as production_router
from app.routers.admin_flags import router as admin_flags_router
from app.routers.cost import router as cost_router

__all__ = [
    "auth_router",
    "me_router",
    "files_router",
    "scenes_router",
    "exports_router",
    "voices_router",
    "templates_router",
    "assets_router",
    "characters_router",
    "playground_router",
    "brand_kits_router",
    "team_router",
    "billing_router",
    "rewards_router",
    "ai_router",
    "pipelines_router",
    "production_router",
    "dlq_router",
    "admin_flags_router",
    "cost_router",
]
