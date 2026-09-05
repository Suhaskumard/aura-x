"""
Phase 10/11 REST API: repository ingestion and browsing endpoints.

POST /repositories and POST /{id}/refresh perform the fast synchronous
part of ingestion (URL validation through metadata fetch) inline, then
dispatch the slow part (branch resolution, clone, scan) to a
BackgroundTasks callback and return 202 Accepted immediately -- the
response body reflects the run's state at creation time, not its final
outcome. Poll GET /analysis-runs/{id} for that.

Every domain error is translated to an HTTP response by
app.api.error_handlers, registered globally in app.main -- handlers here
never construct their own error JSON bodies.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.session import get_db
from app.domain.errors import RepositoryNotFoundError
from app.domain.repository_provider import get_provider_class_for_host
from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.models.repository import Repository
from app.services import persistence_service
from app.services.context_builder import build_repository_context
from app.services.excel_report_service import generate_repository_report
from app.services.ingestion_service import continue_ingestion, start_ingestion

from app.api.v1.schemas import (
    AnalysisRunResponse,
    BranchResponse,
    CommitResponse,
    IngestRepositoryRequest,
    IngestRepositoryResponse,
    PaginatedRepositoriesResponse,
    RefreshRepositoryRequest,
    RepositoryResponse,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])
runs_router = APIRouter(prefix="/analysis-runs", tags=["analysis-runs"])


def _get_repository_or_404(session: Session, repository_id: str) -> Repository:
    repository = session.get(Repository, repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"Repository '{repository_id}' not found")
    return repository


def _get_analysis_run_or_404(session: Session, run_id: int) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise RepositoryNotFoundError(f"AnalysisRun '{run_id}' not found")
    return run


def _session_factory_for(session: Session):
    # A background task must never reuse the request-scoped session (see
    # ingestion_service.py's docstring), but it must write to the SAME
    # database -- derive a fresh sessionmaker from the same engine rather
    # than assuming the production SessionLocal, so this works correctly
    # against whatever engine the request's session is actually bound to
    # (a per-test SQLite file included).
    return sessionmaker(bind=session.get_bind(), autoflush=False, autocommit=False, future=True)


@router.post("", response_model=IngestRepositoryResponse, status_code=202)
def create_repository(
    payload: IngestRepositoryRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_db)
):
    settings = get_settings()
    run, parsed = start_ingestion(
        session, source_url=payload.source_url, requested_branch=payload.branch, settings=settings
    )
    background_tasks.add_task(
        continue_ingestion,
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=payload.branch,
        settings=settings,
        session_factory=_session_factory_for(session),
    )
    repository = session.get(Repository, run.repository_id)
    return IngestRepositoryResponse(
        repository=RepositoryResponse.model_validate(repository),
        analysis_run=AnalysisRunResponse.model_validate(run),
    )


@router.get("", response_model=PaginatedRepositoriesResponse)
def list_repositories(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
):
    total = session.query(Repository).count()
    items = session.query(Repository).order_by(Repository.id).offset(offset).limit(limit).all()
    return PaginatedRepositoriesResponse(
        items=[RepositoryResponse.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(repository_id: str, session: Session = Depends(get_db)):
    repository = _get_repository_or_404(session, repository_id)
    return RepositoryResponse.model_validate(repository)


@router.get("/{repository_id}/branches", response_model=list[BranchResponse])
def list_branches(repository_id: str, session: Session = Depends(get_db)):
    _get_repository_or_404(session, repository_id)
    branches = session.query(Branch).filter(Branch.repository_id == repository_id).order_by(Branch.name).all()
    return [BranchResponse.model_validate(b) for b in branches]


@router.get("/{repository_id}/commits", response_model=list[CommitResponse])
def list_commits(
    repository_id: str,
    branch: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_db),
):
    repository = _get_repository_or_404(session, repository_id)
    settings = get_settings()
    # Repository.provider stores the short provider name ("github"), but
    # the registry is keyed by hostname. Only "github" exists today
    # (Phase 3's registry only ever registers github.com/www.github.com);
    # this mapping will need to grow the day a second provider does.
    hostname = "github.com" if repository.provider == "github" else repository.provider
    provider_cls = get_provider_class_for_host(hostname)
    if provider_cls is None:
        raise RepositoryNotFoundError(f"No provider registered for '{repository.provider}'")
    provider = provider_cls(settings=settings)

    target_branch = branch or repository.default_branch
    commits = provider.get_commit_history(repository.owner, repository.name, target_branch, limit)
    return [
        CommitResponse(
            sha=c.sha, author_name=c.author_name, author_email=c.author_email,
            committed_at=c.committed_at, message=c.message,
        )
        for c in commits
    ]


@router.post("/{repository_id}/refresh", response_model=IngestRepositoryResponse, status_code=202)
def refresh_repository(
    repository_id: str,
    background_tasks: BackgroundTasks,
    payload: RefreshRepositoryRequest = RefreshRepositoryRequest(),
    session: Session = Depends(get_db),
):
    repository = _get_repository_or_404(session, repository_id)
    settings = get_settings()
    run, parsed = start_ingestion(
        session, source_url=repository.source_url, requested_branch=payload.branch, settings=settings
    )
    background_tasks.add_task(
        continue_ingestion,
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=payload.branch,
        settings=settings,
        session_factory=_session_factory_for(session),
    )
    refreshed_repository = session.get(Repository, run.repository_id)
    return IngestRepositoryResponse(
        repository=RepositoryResponse.model_validate(refreshed_repository),
        analysis_run=AnalysisRunResponse.model_validate(run),
    )


@runs_router.get("/{run_id}", response_model=AnalysisRunResponse)
def get_analysis_run(run_id: int, session: Session = Depends(get_db)):
    run = _get_analysis_run_or_404(session, run_id)
    persistence_service.reconcile_stuck_run(session, run=run, settings=get_settings())
    return AnalysisRunResponse.model_validate(run)


@runs_router.get("/{run_id}/export.xlsx")
def export_analysis_run(run_id: int, session: Session = Depends(get_db)):
    _get_analysis_run_or_404(session, run_id)  # 404s before doing any work
    context = build_repository_context(session, run_id=run_id, settings=get_settings())
    workbook_bytes = generate_repository_report(context)
    filename = f"{context.owner}-{context.repository_name}-{run_id}.xlsx"
    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
