"""
Persist a RepositoryContext (Phase 8's fully-assembled ingestion result)
through the Phase 9 data-access layer.

Not yet called from an API route or background worker -- that starts at
Phase 10/11, which will call assemble_repository_context() (Phase 8) and
then persist_repository_context() (this module) in sequence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.repository_dao import (
    complete_analysis_run,
    create_analysis_run,
    fail_analysis_run,
    transition_analysis_run,
    upsert_branches,
    upsert_commits,
    upsert_repository,
)
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.models.analysis_run import AnalysisRun
from app.services.repository_service import build_repository_profile

# The only path to READY in ALLOWED_TRANSITIONS (app/domain/repository_
# context.py) runs through every one of these stages in order -- the
# pipeline has no branching, so a context that reached READY necessarily
# passed through all of them. Replaying that sequence on the persisted
# AnalysisRun (rather than jumping straight to READY) keeps the DB state
# machine honest and exercises the same allow-list Phase 3 enforces
# in-memory. A FAILED context needs no such replay: PENDING -> FAILED is
# itself a valid transition (FAILED is reachable from any non-terminal
# state), so it's recorded as failed without claiming which stage it
# reached first.
_STAGES_BEFORE_READY = [
    IngestionStatus.VALIDATING,
    IngestionStatus.FETCHING_METADATA,
    IngestionStatus.FETCHING_BRANCHES,
    IngestionStatus.CLONING,
    IngestionStatus.SCANNING,
]


def build_config_snapshot(settings: Settings, *, evolution_commit_limit: int) -> dict:
    """Non-secret ingestion configuration for AnalysisRun.config_snapshot --
    exactly what governed this run, for reproducibility. Never includes
    `github_token` or any other secret."""
    return {
        "github_api_base_url": settings.github_api_base_url,
        "github_request_timeout_seconds": settings.github_request_timeout_seconds,
        "github_max_retries": settings.github_max_retries,
        "clone_timeout_seconds": settings.clone_timeout_seconds,
        "max_repository_size_mb": settings.max_repository_size_mb,
        "max_commit_history": settings.max_commit_history,
        "evolution_commit_limit": evolution_commit_limit,
    }


def persist_repository_context(
    db: Session, context: RepositoryContext, *, config_snapshot: dict
) -> AnalysisRun:
    """Write `context` through the Repository/Branch/Commit/AnalysisRun
    tables and return the AnalysisRun row.

    Repository/Branch/Commit reflect the current state of the repository
    (upserted, not appended) regardless of outcome. The AnalysisRun records
    which branch/commit/configuration this specific ingestion attempt used,
    and is completed with the Repository Profile view on READY or failed
    with the structured error on FAILED -- context.analysis_status decides
    which. Mirrors the in-memory status onto the persisted run rather than
    re-deriving it, so the two never disagree.
    """
    repository = upsert_repository(
        db,
        provider=context.provider,
        owner=context.owner,
        name=context.repository_name,
        source_url=context.source_url,
        metadata=context.metadata,
        repository_id=context.repository_id,
    )
    upsert_branches(db, repository, context.branches)
    upsert_commits(db, repository, context.git_history)

    run = create_analysis_run(
        db,
        repository,
        branch_name=context.selected_branch,
        commit_sha=context.commit_sha,
        config_snapshot=config_snapshot,
    )

    if context.analysis_status == IngestionStatus.READY:
        for stage in _STAGES_BEFORE_READY:
            transition_analysis_run(db, run, stage)
        complete_analysis_run(db, run, result_profile=build_repository_profile(context))
    elif context.analysis_status == IngestionStatus.FAILED:
        fail_analysis_run(db, run, context.last_error or {})

    db.commit()
    return run
