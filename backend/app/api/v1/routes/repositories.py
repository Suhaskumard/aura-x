"""
/api/v1/repositories -- ingestion, browsing, and profile endpoints
(Phase 10). Route handlers only: parse/validate the request, call a
service, shape the response. Structured errors from services propagate
as RepositoryIntegrationError and are translated to HTTP responses by
app/api/v1/error_handlers.py -- handlers here never catch or reformat
them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.repository_dao import (
    count_commits,
    count_repositories,
    get_latest_analysis_run,
    get_repository_by_id,
    list_commits,
    list_repositories,
)
from app.db.session import get_db
from app.domain.errors import AnalysisNotReadyError, RepositoryNotFoundError, UnauthorizedError
from app.domain.repository_context import IngestionStatus
from app.models.analysis_run import AnalysisRun
from app.models.repository import Repository
from app.services.ingestion_orchestrator import ingest_github_repository, refresh_repository_ingestion

from app.api.v1.schemas import (
    BranchOut,
    CommitOut,
    ErrorResponse,
    IngestRepositoryRequest,
    IngestRepositoryResponse,
    LatestAnalysisRun,
    PaginatedCommits,
    PaginatedRepositories,
    RefreshRepositoryRequest,
    RepositoryDetail,
    RepositoryProfileResponse,
    RepositorySummary,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "Repository not found"}}
_UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Missing/invalid API auth token"}}
_INVALID_REQUEST = {400: {"model": ErrorResponse, "description": "Invalid or unsupported repository URL"}}


def require_api_auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """No-op when api_auth_token is unset (default, local-dev-friendly).
    When set, mutating routes require `Authorization: Bearer <token>`."""
    if not settings.has_api_auth_token():
        return
    expected = f"Bearer {settings.api_auth_token.get_secret_value()}"
    if authorization != expected:
        raise UnauthorizedError("Missing or invalid Authorization header")


def _get_repository_or_404(db: Session, repository_id: str) -> Repository:
    repository = get_repository_by_id(db, repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"No repository with id {repository_id!r}")
    return repository


def _to_summary(repository: Repository, latest_run: AnalysisRun | None) -> RepositorySummary:
    return RepositorySummary(
        id=repository.id,
        provider=repository.provider,
        owner=repository.owner,
        name=repository.name,
        source_url=repository.source_url,
        default_branch=repository.default_branch,
        description=repository.description,
        visibility=repository.visibility,
        primary_language=repository.primary_language,
        stargazers_count=repository.stargazers_count,
        forks_count=repository.forks_count,
        latest_status=latest_run.status if latest_run else None,
        updated_at=repository.updated_at,
    )


def _to_ingest_response(repository: Repository, run: AnalysisRun) -> IngestRepositoryResponse:
    return IngestRepositoryResponse(
        repository_id=repository.id,
        provider=repository.provider,
        source_url=repository.source_url,
        name=repository.name,
        owner=repository.owner,
        selected_branch=run.branch_name,
        commit_sha=run.commit_sha,
        status=run.status,
        analysis_run_id=run.id,
        error_code=run.error_code,
        error_message=run.error_message,
    )


@router.post(
    "/github",
    response_model=IngestRepositoryResponse,
    status_code=201,
    summary="Ingest a GitHub repository",
    responses={**_INVALID_REQUEST, **_UNAUTHORIZED},
)
def ingest_github_repository_endpoint(
    payload: IngestRepositoryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_api_auth),
) -> IngestRepositoryResponse:
    run = ingest_github_repository(
        db, settings, repository_url=payload.repository_url, branch=payload.branch
    )
    repository = get_repository_by_id(db, run.repository_id)
    return _to_ingest_response(repository, run)


@router.get("", response_model=PaginatedRepositories, summary="List ingested repositories (paginated)")
def list_repositories_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedRepositories:
    total = count_repositories(db)
    rows = list_repositories(db, offset=(page - 1) * page_size, limit=page_size)
    items = [_to_summary(row, get_latest_analysis_run(db, row.id)) for row in rows]
    return PaginatedRepositories(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/{repository_id}",
    response_model=RepositoryDetail,
    summary="Get a repository's details and latest analysis run",
    responses={**_NOT_FOUND},
)
def get_repository_endpoint(repository_id: str, db: Session = Depends(get_db)) -> RepositoryDetail:
    repository = _get_repository_or_404(db, repository_id)
    latest_run = get_latest_analysis_run(db, repository_id)
    summary = _to_summary(repository, latest_run)
    return RepositoryDetail(
        **summary.model_dump(),
        license_name=repository.license_name,
        topics=repository.topics,
        open_issues_count=repository.open_issues_count,
        latest_analysis_run=(
            LatestAnalysisRun(
                id=latest_run.id,
                status=latest_run.status,
                branch_name=latest_run.branch_name,
                commit_sha=latest_run.commit_sha,
                error_code=latest_run.error_code,
                error_message=latest_run.error_message,
                started_at=latest_run.started_at,
                completed_at=latest_run.completed_at,
            )
            if latest_run
            else None
        ),
    )


@router.get(
    "/{repository_id}/branches",
    response_model=list[BranchOut],
    summary="List a repository's known branches",
    responses={**_NOT_FOUND},
)
def get_repository_branches_endpoint(
    repository_id: str, db: Session = Depends(get_db)
) -> list[BranchOut]:
    repository = _get_repository_or_404(db, repository_id)
    return [
        BranchOut(name=b.name, head_commit_sha=b.head_commit_sha, is_default=b.is_default)
        for b in sorted(repository.branches, key=lambda b: (not b.is_default, b.name))
    ]


@router.get(
    "/{repository_id}/profile",
    response_model=RepositoryProfileResponse,
    summary="Get the Repository Profile view from the latest completed analysis",
    responses={
        **_NOT_FOUND,
        409: {"model": ErrorResponse, "description": "No completed (READY) analysis run yet"},
    },
)
def get_repository_profile_endpoint(
    repository_id: str, db: Session = Depends(get_db)
) -> RepositoryProfileResponse:
    repository = _get_repository_or_404(db, repository_id)
    latest_run = get_latest_analysis_run(db, repository_id)
    if (
        latest_run is None
        or latest_run.status != IngestionStatus.READY.value
        or latest_run.result_profile is None
    ):
        status_hint = latest_run.status if latest_run is not None else "NONE"
        raise AnalysisNotReadyError(
            f"No completed analysis available for repository {repository_id!r} (status={status_hint})"
        )
    return RepositoryProfileResponse(
        repository_id=repository.id,
        analysis_run_id=latest_run.id,
        status=latest_run.status,
        profile=latest_run.result_profile,
        completed_at=latest_run.completed_at,
    )


@router.get(
    "/{repository_id}/commits",
    response_model=PaginatedCommits,
    summary="List a repository's known commit history (paginated)",
    responses={**_NOT_FOUND},
)
def get_repository_commits_endpoint(
    repository_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> PaginatedCommits:
    _get_repository_or_404(db, repository_id)
    total = count_commits(db, repository_id)
    rows = list_commits(db, repository_id, offset=(page - 1) * page_size, limit=page_size)
    items = [
        CommitOut(
            sha=c.sha,
            author_name=c.author_name,
            author_email=c.author_email,
            committed_at=c.committed_at,
            message=c.message,
            additions=c.additions,
            deletions=c.deletions,
        )
        for c in rows
    ]
    return PaginatedCommits(items=items, total=total, page=page, page_size=page_size)


@router.post(
    "/{repository_id}/refresh",
    response_model=IngestRepositoryResponse,
    summary="Re-ingest an already-known repository",
    responses={**_NOT_FOUND, **_UNAUTHORIZED},
)
def refresh_repository_endpoint(
    repository_id: str,
    payload: RefreshRepositoryRequest | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _auth: None = Depends(require_api_auth),
) -> IngestRepositoryResponse:
    branch = payload.branch if payload is not None else None
    run = refresh_repository_ingestion(db, settings, repository_id=repository_id, branch=branch)
    repository = get_repository_by_id(db, run.repository_id)
    return _to_ingest_response(repository, run)
