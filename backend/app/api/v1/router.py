"""
Top-level /api/v1 router.
"""

from fastapi import APIRouter

from app.api.v1.routes.repositories import router as repositories_router
from app.core.config import get_settings

api_router = APIRouter()
api_router.include_router(repositories_router)


@api_router.get("/health", tags=["system"])
def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.environment,
        "github_token_configured": settings.has_github_token(),
    }
