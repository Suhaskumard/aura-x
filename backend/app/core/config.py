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

    # Database
    database_url: str = Field(
        default="postgresql+psycopg://aurax:aurax@localhost:5432/aurax",
    )

    # API authentication (Phase 10). Optional, opt-in, same SecretStr
    # pattern as github_token below -- when unset (the default), API auth
    # is not enforced (matches this project's local-dev-friendly stance);
    # set it to require `Authorization: Bearer <token>` on mutating
    # /api/v1/repositories routes.
    api_auth_token: SecretStr | None = Field(default=None)

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

    def has_github_token(self) -> bool:
        return self.github_token is not None and bool(self.github_token.get_secret_value())

    def has_api_auth_token(self) -> bool:
        return self.api_auth_token is not None and bool(self.api_auth_token.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
