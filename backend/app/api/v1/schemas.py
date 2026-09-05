"""Pydantic request/response models for the Phase 10 REST API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IngestRepositoryRequest(BaseModel):
    source_url: str
    branch: str | None = None


class RefreshRepositoryRequest(BaseModel):
    branch: str | None = None


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    source_url: str
    owner: str
    name: str
    default_branch: str | None
    description: str | None
    visibility: str
    primary_language: str | None
    license_name: str | None
    stargazers_count: int
    forks_count: int
    open_issues_count: int
    created_at: datetime
    updated_at: datetime


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    head_commit_sha: str
    is_default: bool


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: str
    branch_id: int | None
    requested_branch: str | None
    commit_sha: str | None
    status: str
    last_error: dict | None
    created_at: datetime
    updated_at: datetime


class IngestRepositoryResponse(BaseModel):
    """Returned by POST /repositories and POST /{id}/refresh (202
    Accepted, Phase 11). analysis_run.status reflects the run's state at
    creation time (typically FETCHING_METADATA) -- ingestion continues in
    a background task after this response is sent, so this is NOT the
    final outcome. Poll GET /analysis-runs/{id} for that."""

    repository: RepositoryResponse
    analysis_run: AnalysisRunResponse


class CommitResponse(BaseModel):
    sha: str
    author_name: str | None
    author_email: str | None
    committed_at: datetime | None
    message: str


class PaginatedRepositoriesResponse(BaseModel):
    items: list[RepositoryResponse]
    total: int
    limit: int
    offset: int
