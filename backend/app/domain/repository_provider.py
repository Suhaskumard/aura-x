"""
RepositoryProvider: the abstraction every source-control backend
(GitHub now; GitLab, a purely local path, etc. in the future) implements.
Nothing outside app/services may depend on a concrete provider directly —
callers should go through get_provider_for_host() and program against
this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileChange, RepositoryMetadata


class RepositoryProvider(ABC):
    """Abstract source-control provider. See docs/GITHUB_INTEGRATION.md."""

    #: short machine-readable identifier stored on RepositoryContext.provider
    name: str

    @abstractmethod
    def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        ...

    @abstractmethod
    def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
        ...

    @abstractmethod
    def get_commit_history(
        self, owner: str, repo: str, branch: str, limit: int
    ) -> list[CommitInfo]:
        ...

    @abstractmethod
    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        ...

    @abstractmethod
    def get_commit_file_changes(self, owner: str, repo: str, sha: str) -> list[FileChange]:
        """Per-file additions/deletions/status for a single commit. Not
        included in get_commit_history's bulk listing (Phase 6) -- callers
        that need this for evolution analysis (Phase 8) fetch it for a
        bounded subset of commits, see
        app/services/repository_service.py::enrich_commit_history."""
        ...

    @abstractmethod
    def clone(self, owner: str, repo: str, branch: str, target_dir: str) -> CloneResult:
        ...


# Registry mapping a normalized hostname to the provider class that
# handles it. Populated by concrete provider modules calling
# register_provider() at import time (see app/services/github_provider.py,
# introduced in Phase 5) so this module stays free of provider-specific
# imports.
_PROVIDER_REGISTRY: dict[str, type[RepositoryProvider]] = {}


def register_provider(hostname: str, provider_cls: type[RepositoryProvider]) -> None:
    _PROVIDER_REGISTRY[hostname.lower()] = provider_cls


def get_provider_class_for_host(hostname: str) -> type[RepositoryProvider] | None:
    return _PROVIDER_REGISTRY.get(hostname.lower())


def registered_hosts() -> list[str]:
    return sorted(_PROVIDER_REGISTRY.keys())
