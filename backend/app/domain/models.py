"""
Provider-agnostic value types shared by RepositoryProvider implementations
and RepositoryContext. None of these types import a GitHub SDK, an ORM, or
any network client — they must be constructible and testable with zero
external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RepositoryMetadata:
    repository_id: str
    name: str
    owner: str
    description: str | None
    default_branch: str
    visibility: str  # "public" | "private"
    primary_language: str | None
    topics: list[str] = field(default_factory=list)
    license_name: str | None = None
    stargazers_count: int = 0
    forks_count: int = 0
    open_issues_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BranchInfo:
    name: str
    head_commit_sha: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    parents: list[str]
    author_name: str | None
    author_email: str | None
    committed_at: datetime | None
    message: str
    additions: int | None = None
    deletions: int | None = None
    changed_files: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FileEntry:
    relative_path: str
    extension: str
    size_bytes: int
    category: str  # "source" | "test" | "docs" | "config" | "build" | "dependency" | "other"
    language: str | None = None


@dataclass(frozen=True, slots=True)
class CloneResult:
    local_path: str
    commit_sha: str
    branch: str
    cloned_at: datetime
