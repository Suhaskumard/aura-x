"""
Top-level /api/v1 router.

Route modules for repository ingestion (POST/GET /repositories, ...) are
added starting Phase 10. Phase 0 only registers a health check so the
service is provably running end-to-end.
"""

from fastapi import APIRouter

from app.core.config import get_settings

api_router = APIRouter()


@api_router.get("/health", tags=["system"])
def health_check() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.environment,
        "github_token_configured": settings.has_github_token(),
    }
