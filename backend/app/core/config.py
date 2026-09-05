"""
Centralized application settings.

All configuration is loaded from environment variables (optionally via a
local .env file during development). Secrets such as GITHUB_TOKEN must
never be logged or serialized back to clients — see docs/GITHUB_INTEGRATION.md.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AURA-X"
    environment: str = Field(default="development")
    api_v1_prefix: str = "/api/v1"

    # Database. Defaults to a local SQLite file for early development (per
    # the project plan's own allowance); override via .env/DATABASE_URL to
    # point at a real Postgres instance for production, e.g.
    # "postgresql+psycopg://aurax:aurax@localhost:5432/aurax".
    database_url: str = Field(
        default=f"sqlite:///{BACKEND_ROOT / '.workspace' / 'aurax.db'}",
    )

    # GitHub integration (backend-only secret; never returned to clients)
    github_token: SecretStr | None = Field(default=None)
    github_api_base_url: str = Field(default="https://api.github.com")
    github_request_timeout_seconds: float = Field(default=10.0)
    github_max_retries: int = Field(default=3)

    # Repository ingestion / clone sandbox
    workspace_root: Path = Field(default=BACKEND_ROOT / ".workspace" / "repositories")
    clone_timeout_seconds: int = Field(default=120)
    max_repository_size_mb: int = Field(default=500)
    max_commit_history: int = Field(default=200)

    # Repository scanning (Phase 8)
    scan_history_depth: int = Field(default=50)
    max_scan_file_count: int = Field(default=50_000)

    # Async ingestion (Phase 11): a run stuck in a non-terminal state for
    # longer than this (e.g. a crashed background task) is force-failed
    # the next time it's polled.
    stuck_run_timeout_seconds: int = Field(default=600)

    def has_github_token(self) -> bool:
        return self.github_token is not None and bool(self.github_token.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
