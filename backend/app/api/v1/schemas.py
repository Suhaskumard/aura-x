"""
Pydantic request/response models for /api/v1/repositories (Phase 10,
extended in Phase 11).

Kept separate from the ORM models (app/models/) -- these describe the
wire format, not the storage schema, and never expose a local filesystem
path or a secret. Every `status` field here carries the public status
vocabulary (QUEUED/VALIDATING/FETCHING/CLONING/ANALYZING/READY/FAILED,
see app.api.v1.status_mapping.to_public_status), not the internal
IngestionStatus values AnalysisRun.status is persisted as.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IngestRepositoryRequest(BaseModel):
    repository_url: str = Field(..., description="A GitHub repository URL, e.g. https://github.com/owner/repo")
    branch: str | None = Field(default=None, description="Branch to analyze; defaults to the repository's default branch")


class RefreshRepositoryRequest(BaseModel):
    branch: str | None = Field(default=None, description="Branch to analyze; defaults to the repository's default branch")


class IngestRepositoryResponse(BaseModel):
    """Returned immediately on enqueue (Phase 11) -- status is QUEUED and
    selected_branch/commit_sha are still null at this point (not resolved
    yet); poll analysis_run_id via GET .../analysis-runs/{id} or GET
    .../{repository_id} for live progress."""

    repository_id: str
    provider: str
    source_url: str
    name: str
    owner: str
    selected_branch: str | None
    commit_sha: str | None
    status: str
    analysis_run_id: str
    error_code: str | None = None
    error_message: str | None = None


class AnalysisRunStatus(BaseModel):
    id: str
    repository_id: str
    status: str
    branch_name: str | None
    commit_sha: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class RepositorySummary(BaseModel):
    id: str
    provider: str
    owner: str
    name: str
    source_url: str
    default_branch: str | None
    description: str | None
    visibility: str | None
    primary_language: str | None
    stargazers_count: int
    forks_count: int
    latest_status: str | None
    updated_at: datetime


class PaginatedRepositories(BaseModel):
    items: list[RepositorySummary]
    total: int
    page: int
    page_size: int


class LatestAnalysisRun(BaseModel):
    id: str
    status: str
    branch_name: str | None
    commit_sha: str | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class RepositoryDetail(RepositorySummary):
    license_name: str | None
    topics: list[str]
    open_issues_count: int
    latest_analysis_run: LatestAnalysisRun | None


class BranchOut(BaseModel):
    name: str
    head_commit_sha: str
    is_default: bool


class CommitOut(BaseModel):
    sha: str
    author_name: str | None
    author_email: str | None
    committed_at: datetime | None
    message: str
    additions: int | None
    deletions: int | None


class PaginatedCommits(BaseModel):
    items: list[CommitOut]
    total: int
    page: int
    page_size: int


class RepositoryProfileResponse(BaseModel):
    repository_id: str
    analysis_run_id: str
    status: str
    profile: dict
    completed_at: datetime | None


class ErrorResponse(BaseModel):
    code: str
    message: str
