"""FastAPI application entrypoint for the AURA-X backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.error_handlers import register_error_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Autonomous Unified Reliability & Evolution Analyzer",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)
register_error_handlers(app)


@app.get("/", tags=["system"])
def root() -> dict:
    return {"service": settings.app_name, "docs": "/docs"}
