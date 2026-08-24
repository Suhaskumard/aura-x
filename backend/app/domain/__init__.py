"""
Provider-agnostic domain layer.

RepositoryProvider (abstraction), RepositoryContext (normalized model),
shared value types, and the structured error taxonomy live here. No
module in this package may import a GitHub SDK, HTTP client, ORM, or the
FastAPI app — see docs/GITHUB_INTEGRATION.md "Architecture".
"""

from app.domain.errors import RepositoryIntegrationError
from app.domain.models import (
    BranchInfo,
    CloneResult,
    CommitInfo,
    FileEntry,
    RepositoryMetadata,
)
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import RepositoryProvider, get_provider_class_for_host

__all__ = [
    "RepositoryIntegrationError",
    "BranchInfo",
    "CloneResult",
    "CommitInfo",
    "FileEntry",
    "RepositoryMetadata",
    "IngestionStatus",
    "RepositoryContext",
    "RepositoryProvider",
    "get_provider_class_for_host",
]
