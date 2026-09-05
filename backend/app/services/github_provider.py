"""
GitHubProvider: the concrete RepositoryProvider for github.com.

Wraps GitHubApiClient and translates raw GitHub JSON into the
provider-agnostic domain types in app/domain/models.py. Registered against
"github.com" and "www.github.com" at import time so
get_provider_class_for_host() can resolve it -- see
app/domain/repository_provider.py.

clone() (Phase 7) clones a public repository via app/services/clone_service.py
-- the only module allowed to spawn a subprocess. Private-repo cloning is
not supported (see clone_service.py module docstring for why).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.domain.models import BranchInfo, CloneResult, CommitInfo, RepositoryMetadata
from app.domain.repository_provider import RepositoryProvider, register_provider
from app.services import clone_service
from app.services.github_client import GitHubApiClient


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_repository_metadata(payload: dict) -> RepositoryMetadata:
    owner = payload.get("owner") or {}
    license_info = payload.get("license") or {}
    return RepositoryMetadata(
        repository_id=str(payload["id"]),
        name=payload["name"],
        owner=owner.get("login", ""),
        description=payload.get("description"),
        default_branch=payload.get("default_branch", "main"),
        visibility="private" if payload.get("private") else "public",
        primary_language=payload.get("language"),
        topics=list(payload.get("topics") or []),
        license_name=license_info.get("name"),
        stargazers_count=payload.get("stargazers_count", 0) or 0,
        forks_count=payload.get("forks_count", 0) or 0,
        open_issues_count=payload.get("open_issues_count", 0) or 0,
        created_at=_parse_github_datetime(payload.get("created_at")),
        updated_at=_parse_github_datetime(payload.get("updated_at")),
    )


def _to_branch_info(payload: dict, *, default_branch: str) -> BranchInfo:
    name = payload["name"]
    commit = payload.get("commit") or {}
    return BranchInfo(
        name=name,
        head_commit_sha=commit.get("sha", ""),
        is_default=(name == default_branch),
    )


def _to_commit_info(payload: dict) -> CommitInfo:
    commit = payload.get("commit") or {}
    author = commit.get("author") or {}
    parents = [p.get("sha", "") for p in (payload.get("parents") or [])]
    return CommitInfo(
        sha=payload.get("sha", ""),
        parents=parents,
        author_name=author.get("name"),
        author_email=author.get("email"),
        committed_at=_parse_github_datetime(author.get("date")),
        message=commit.get("message", ""),
    )


class GitHubProvider(RepositoryProvider):
    name = "github"

    def __init__(self, settings: Settings | None = None, client: GitHubApiClient | None = None):
        self._settings = settings or get_settings()
        self._client = client or GitHubApiClient(settings=self._settings)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GitHubProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        payload = self._client.get_json(f"/repos/{owner}/{repo}")
        return _to_repository_metadata(payload)

    def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
        metadata = self.fetch_metadata(owner, repo)
        payloads = self._client.get_paginated(f"/repos/{owner}/{repo}/branches", limit=1000)
        return [_to_branch_info(p, default_branch=metadata.default_branch) for p in payloads]

    def get_commit_history(
        self, owner: str, repo: str, branch: str, limit: int
    ) -> list[CommitInfo]:
        bounded_limit = min(limit, self._settings.max_commit_history)
        payloads = self._client.get_paginated(
            f"/repos/{owner}/{repo}/commits",
            limit=bounded_limit,
            params={"sha": branch},
        )
        return [_to_commit_info(p) for p in payloads]

    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        payload = self._client.get_json(f"/repos/{owner}/{repo}/languages")
        return dict(payload) if isinstance(payload, dict) else {}

    def clone(self, owner: str, repo: str, branch: str, target_dir: str) -> CloneResult:
        clone_url = f"https://github.com/{owner}/{repo}.git"
        return clone_service.run_git_clone(
            clone_url=clone_url,
            branch=branch,
            target_dir=Path(target_dir),
            settings=self._settings,
        )


register_provider("github.com", GitHubProvider)
register_provider("www.github.com", GitHubProvider)
