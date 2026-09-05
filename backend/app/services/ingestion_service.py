"""
Repository ingestion orchestration.

Ties together every phase built so far (URL validation, GitHub API,
branch resolution, secure cloning, scanning, persistence). Split into
two parts at the seam Phase 10 already had:

- start_ingestion() is the fast synchronous part (URL parse through
  fetching metadata and creating the AnalysisRun row) -- errors here
  (bad URL, repo not found) are pure HTTP errors, no durable row exists
  yet for a malformed URL.
- continue_ingestion() is the slow part (branch resolution, clone, scan)
  meant to run in a FastAPI BackgroundTasks callback, scheduled by the
  API layer after start_ingestion() returns. It opens its OWN fresh
  database session -- it must never receive the original request's
  Session by reference, since app.db.session.get_db()'s generator
  dependency closes that session once the endpoint returns, which can
  race with a background task still using it.

Any failure in continue_ingestion() transitions the run to FAILED with
the structured error recorded, then swallows the exception (a background
task's unhandled exception is silently dropped by Starlette -- there is
no request left to propagate it to).

Known accepted gap: each persistence_service function commits
internally, so there is no single transaction spanning the whole
pipeline. A process crash mid-ingestion leaves a run stuck at a
non-terminal status with no FAILED transition ever recorded -- not
corrupt, just stale. See persistence_service.reconcile_stuck_run(),
triggered as a check-on-read from the polling endpoints rather than a
scheduled sweep (no scheduler exists).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.domain.errors import RepositoryIntegrationError, UnsupportedRepositoryProviderError
from app.domain.github_url import ParsedGitHubUrl, parse_github_url
from app.domain.repository_context import IngestionStatus
from app.domain.repository_provider import RepositoryProvider, get_provider_class_for_host
from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.services import persistence_service
from app.services.clone_service import clone_repository
from app.services.context_builder import scan_result_to_dict
from app.services.repository_scan_service import scan_repository
from app.services.repository_service import resolve_branch

logger = logging.getLogger(__name__)


def _resolve_provider(hostname: str, settings: Settings) -> RepositoryProvider:
    provider_cls = get_provider_class_for_host(hostname)
    if provider_cls is None:
        raise UnsupportedRepositoryProviderError(f"Unsupported repository provider host: {hostname}")
    return provider_cls(settings=settings)


def start_ingestion(
    session,
    *,
    source_url: str,
    requested_branch: str | None,
    settings: Settings | None = None,
) -> tuple[AnalysisRun, ParsedGitHubUrl]:
    """Fast synchronous part: URL validation through metadata fetch and
    AnalysisRun creation. Returns the run (state FETCHING_METADATA) plus
    the parsed URL, for the caller to hand off to continue_ingestion()."""
    settings = settings or get_settings()

    parsed = parse_github_url(source_url)
    provider = _resolve_provider("github.com", settings)

    metadata = provider.fetch_metadata(parsed.owner, parsed.repository)
    repository = persistence_service.get_or_create_repository(
        session, metadata=metadata, provider=provider.name, source_url=parsed.normalized_url
    )

    run = persistence_service.create_analysis_run(
        session, repository_id=repository.id, requested_branch=requested_branch
    )
    persistence_service.transition_analysis_run(session, run=run, new_status=IngestionStatus.VALIDATING)
    persistence_service.transition_analysis_run(session, run=run, new_status=IngestionStatus.FETCHING_METADATA)

    return run, parsed


def continue_ingestion(
    run_id: int,
    *,
    owner: str,
    repo: str,
    requested_branch: str | None,
    settings: Settings | None = None,
    session_factory=None,
) -> None:
    """Slow part: branch resolution through scan. Runs in a background
    task with its own fresh session -- never share the request's Session
    across this boundary. `session_factory` defaults to the real
    production SessionLocal; tests inject one bound to a per-test engine."""
    settings = settings or get_settings()
    session_factory = session_factory or SessionLocal
    session = session_factory()
    try:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            logger.error("continue_ingestion: AnalysisRun %s not found", run_id)
            return

        provider = _resolve_provider("github.com", settings)

        try:
            persistence_service.transition_analysis_run(
                session, run=run, new_status=IngestionStatus.FETCHING_BRANCHES
            )

            branches = provider.list_branches(owner, repo)
            persistence_service.upsert_branches(session, repository_id=run.repository_id, branches=branches)

            resolved_branch = resolve_branch(provider, owner, repo, requested_branch)
            branch_row = (
                session.query(Branch)
                .filter(Branch.repository_id == run.repository_id, Branch.name == resolved_branch.name)
                .one()
            )
            persistence_service.set_analysis_run_branch(session, run=run, branch_id=branch_row.id)

            persistence_service.transition_analysis_run(session, run=run, new_status=IngestionStatus.CLONING)
            clone_result = clone_repository(
                provider=provider,
                repository_id=run.repository_id,
                owner=owner,
                repo=repo,
                branch=resolved_branch.name,
                settings=settings,
            )
            persistence_service.set_analysis_run_commit_sha(
                session, run=run, commit_sha=clone_result.commit_sha
            )

            persistence_service.transition_analysis_run(session, run=run, new_status=IngestionStatus.SCANNING)
            github_languages = provider.get_languages(owner, repo)
            scan_result = scan_repository(
                local_path=Path(clone_result.local_path),
                github_languages=github_languages,
                settings=settings,
            )
            persistence_service.set_analysis_run_scan_result(
                session, run=run, scan_result=scan_result_to_dict(scan_result)
            )

            persistence_service.transition_analysis_run(session, run=run, new_status=IngestionStatus.READY)
        except RepositoryIntegrationError as exc:
            persistence_service.transition_analysis_run(
                session, run=run, new_status=IngestionStatus.FAILED, error=exc.to_dict()
            )
        except Exception:  # noqa: BLE001 -- last resort: never let a background task crash silently unrecorded
            logger.exception("continue_ingestion: unexpected failure for AnalysisRun %s", run_id)
            persistence_service.transition_analysis_run(
                session,
                run=run,
                new_status=IngestionStatus.FAILED,
                error={"code": "UNEXPECTED_ERROR", "message": "An unexpected error occurred during ingestion"},
            )
        finally:
            provider.close()
    finally:
        session.close()
