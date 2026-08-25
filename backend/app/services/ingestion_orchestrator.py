"""
Asynchronous ingestion orchestration (Phase 11).

Two halves, matching FastAPI's BackgroundTasks split:

- enqueue_ingestion() / enqueue_refresh() -- fast and synchronous. Validate
  the URL, upsert a minimal Repository row, create a PENDING AnalysisRun,
  and return immediately. This is all a route handler does before
  responding -- the frontend is never blocked on the actual pipeline.
- run_ingestion_job() -- the real pipeline (Phase 4-8), run as a
  BackgroundTask after the HTTP response has already been sent. Opens its
  own DB session (via an injected `session_factory`, not the request's
  now-closed one) and transitions the persisted AnalysisRun.status live,
  at each stage boundary, exactly when that stage genuinely starts --
  never a replay after the fact, so a concurrent GET sees real progress.

A malformed/unsupported URL fails fast in enqueue_ingestion() with
nothing persisted (there's no valid owner/repo to record yet). Every
failure from FETCHING_METADATA onward happens inside run_ingestion_job()
and is captured onto the already-persisted AnalysisRun as FAILED with a
structured error -- see docs/GITHUB_INTEGRATION.md "Database Persistence"
for why that's diagnosable rather than a silent hang.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.analysis.pipeline import run_downstream_analysis
from app.core.config import Settings
from app.db.repository_dao import (
    complete_analysis_run,
    create_analysis_run,
    fail_analysis_run,
    get_analysis_run,
    get_repository_by_id,
    transition_analysis_run,
    upsert_branches,
    upsert_commits,
    upsert_repository,
)
from app.domain.errors import (
    RepositoryIntegrationError,
    RepositoryNotFoundError,
    UnsupportedRepositoryProviderError,
)
from app.domain.github_url import parse_github_url
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import get_provider_class_for_host
from app.models.analysis_run import AnalysisRun
from app.services.clone_service import remove_workspace
from app.services.ingestion_persistence import build_config_snapshot
from app.services.repository_service import (
    DEFAULT_EVOLUTION_COMMIT_LIMIT,
    assemble_repository_context,
    build_clone_target_dir,
    build_repository_profile,
    select_branch,
)

logger = logging.getLogger(__name__)

# This module lives inside the app.services package, so importing it
# already runs app/services/__init__.py first, which registers
# GitHubProvider (and any future provider) against
# app.domain.repository_provider -- _provider_class_for_source_url() below
# always sees it.


def _provider_class_for_source_url(source_url: str):
    provider_cls = get_provider_class_for_host(urlparse(source_url).hostname or "")
    if provider_cls is None:  # pragma: no cover - parse_github_url already restricts the host set
        raise UnsupportedRepositoryProviderError(f"No provider registered for {source_url}")
    return provider_cls


def enqueue_ingestion(
    db: Session, settings: Settings, *, repository_url: str, branch: str | None
) -> AnalysisRun:
    """Validate `repository_url`, upsert the Repository row, and create a
    PENDING AnalysisRun. Fast -- no network/filesystem access. Hand the
    returned run's id to run_ingestion_job() (as a background task) to
    actually perform the ingestion."""
    parsed = parse_github_url(repository_url)  # raises before anything is persisted
    provider_cls = _provider_class_for_source_url(parsed.normalized_url)

    repository = upsert_repository(
        db,
        provider=provider_cls.name,
        owner=parsed.owner,
        name=parsed.repository,
        source_url=parsed.normalized_url,
        repository_id=str(uuid4()),
    )
    config_snapshot = build_config_snapshot(settings, evolution_commit_limit=DEFAULT_EVOLUTION_COMMIT_LIMIT)
    run = create_analysis_run(
        db, repository, branch_name=branch, commit_sha=None, config_snapshot=config_snapshot
    )
    db.commit()
    return run


def enqueue_refresh(
    db: Session, settings: Settings, *, repository_id: str, branch: str | None
) -> AnalysisRun:
    """Same as enqueue_ingestion(), but for an already-known repository --
    reuses its stored source_url, adding a new AnalysisRun rather than
    creating a duplicate Repository row."""
    repository = get_repository_by_id(db, repository_id)
    if repository is None:
        raise RepositoryNotFoundError(f"No repository with id {repository_id!r}")
    return enqueue_ingestion(db, settings, repository_url=repository.source_url, branch=branch)


def _advance(db: Session, run: AnalysisRun, context: RepositoryContext, status: IngestionStatus) -> None:
    """Transition both the persisted AnalysisRun and the in-memory
    RepositoryContext to `status` together and commit, so a concurrent
    GET observes this stage the moment it genuinely starts."""
    transition_analysis_run(db, run, status)
    context.transition_to(status)
    db.commit()


def _hand_off_to_downstream_analysis(context: RepositoryContext) -> None:
    """Run the Phase 12 downstream analysis stages (Repository
    Intelligence, Evolution Analysis, Dependency Analysis, Risk
    Assessment, Test Planning) against the just-completed context -- the
    "hand off to downstream analysis" step of the full pipeline (Phase
    16). Not persisted or exposed via the API yet (see
    docs/GITHUB_INTEGRATION.md "Downstream analysis" for that scope
    decision); this proves the hand-off itself is real, not skipped, by
    actually running it and logging a summary. Deliberately never allowed
    to affect the AnalysisRun's outcome -- ingestion has already
    succeeded by the time this runs, and a bug in an unrelated downstream
    module must not turn that into a failure.
    """
    try:
        result = run_downstream_analysis(context)
    except Exception:  # noqa: BLE001 - analysis failures must never affect ingestion's own outcome
        logger.exception(
            "Downstream analysis failed for %s/%s (commit %s) -- ingestion result is unaffected",
            context.owner,
            context.repository_name,
            context.commit_sha,
        )
        return

    logger.info(
        "Downstream analysis complete for %s/%s (commit %s): primary_language=%s size=%s "
        "churn_pattern=%s high_risk_files=%d test_recommendations=%d dependencies=%d",
        context.owner,
        context.repository_name,
        context.commit_sha,
        result.intelligence.primary_language,
        result.intelligence.size_classification,
        result.evolution.churn_pattern,
        len(result.risk.high_risk_files),
        len(result.test_planning.recommendations),
        result.dependencies.dependency_count,
    )


def run_ingestion_job(run_id: str, *, settings: Settings, session_factory: sessionmaker) -> None:
    """The actual ingestion pipeline for an already-enqueued AnalysisRun.
    Meant to run as a FastAPI BackgroundTask -- opens its own session via
    `session_factory` (see app.db.session.get_session_factory) since the
    request that enqueued this has already returned its response by the
    time this runs."""
    db = session_factory()
    try:
        run = get_analysis_run(db, run_id)
        if run is None:  # pragma: no cover - defensive; the row was just created by enqueue_ingestion
            return
        repository = get_repository_by_id(db, run.repository_id)
        requested_branch = run.branch_name  # None means "use the default branch"

        context = RepositoryContext(
            repository_id=repository.id,
            provider=repository.provider,
            source_url=repository.source_url,
            owner=repository.owner,
            repository_name=repository.name,
        )
        evolution_commit_limit = run.config_snapshot.get("evolution_commit_limit", DEFAULT_EVOLUTION_COMMIT_LIMIT)

        provider = None
        try:
            provider_cls = _provider_class_for_source_url(repository.source_url)
            provider = provider_cls(settings=settings)

            _advance(db, run, context, IngestionStatus.VALIDATING)

            _advance(db, run, context, IngestionStatus.FETCHING_METADATA)
            context.metadata = provider.fetch_metadata(context.owner, context.repository_name)
            context.default_branch = context.metadata.default_branch
            upsert_repository(
                db,
                provider=repository.provider,
                owner=repository.owner,
                name=repository.name,
                source_url=repository.source_url,
                metadata=context.metadata,
                repository_id=repository.id,
            )
            db.commit()

            _advance(db, run, context, IngestionStatus.FETCHING_BRANCHES)
            context.branches = provider.list_branches(context.owner, context.repository_name)
            selected = select_branch(context.branches, requested_branch)
            context.selected_branch = selected.name
            run.branch_name = selected.name  # record the resolved branch, not just what was requested
            upsert_branches(db, repository, context.branches)
            context.git_history = provider.get_commit_history(
                context.owner, context.repository_name, selected.name, limit=settings.max_commit_history
            )
            context.languages = provider.get_languages(context.owner, context.repository_name)
            db.commit()

            _advance(db, run, context, IngestionStatus.CLONING)
            target_dir = build_clone_target_dir(settings, context.owner, context.repository_name)
            clone_result = provider.clone(context.owner, context.repository_name, selected.name, target_dir)
            context.local_path = clone_result.local_path
            context.commit_sha = clone_result.commit_sha
            run.commit_sha = clone_result.commit_sha
            db.commit()

            # assemble_repository_context() transitions the in-memory
            # context CLONING -> SCANNING -> READY/FAILED itself (Phase
            # 8's own contract) -- only the persisted side is mirrored
            # here, so it isn't double-transitioned.
            transition_analysis_run(db, run, IngestionStatus.SCANNING)
            db.commit()
            assemble_repository_context(context, provider=provider, evolution_commit_limit=evolution_commit_limit)

            upsert_commits(db, repository, context.git_history)
            if context.analysis_status == IngestionStatus.READY:
                complete_analysis_run(db, run, result_profile=build_repository_profile(context))
                _hand_off_to_downstream_analysis(context)
            else:
                fail_analysis_run(db, run, context.last_error or {})
            db.commit()
        except RepositoryIntegrationError as exc:
            fail_analysis_run(db, run, exc.to_dict())
            db.commit()
        except Exception:
            # A bug, or something outside the RepositoryIntegrationError
            # taxonomy (e.g. a DB IntegrityError from a unique-constraint
            # race between two concurrent runs for the same repository),
            # must still resolve this AnalysisRun to FAILED rather than
            # propagate out of a BackgroundTask uncaught -- an uncaught
            # exception here is silently logged by the server with no
            # caller to observe it, leaving the run stuck at whatever
            # status it last reached forever (see module docstring).
            logger.exception(
                "Unexpected error during ingestion for AnalysisRun %s (repository %s/%s) -- marking FAILED",
                run.id,
                context.owner,
                context.repository_name,
            )
            db.rollback()  # the session may hold a failed flush/transaction
            fail_analysis_run(
                db, run, {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred during ingestion."}
            )
            db.commit()
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
            # The cloned working tree (Phase 7) has no purpose once this
            # function returns -- everything that reads it from disk
            # (file scanning, dependency/test-framework detection, the
            # Phase 16 downstream-analysis hand-off above) already ran
            # synchronously within this same call, and the persisted
            # result_profile/downstream reports carry forward everything
            # derived from it. Leaving it on disk after every single
            # ingestion/refresh -- success or failure -- is pure,
            # unbounded workspace_root growth with nothing to reclaim it.
            if context.local_path:
                try:
                    remove_workspace(context.local_path)
                except OSError:
                    logger.warning(
                        "Failed to remove ingestion workspace %s for %s/%s",
                        context.local_path,
                        context.owner,
                        context.repository_name,
                        exc_info=True,
                    )
    finally:
        db.close()
