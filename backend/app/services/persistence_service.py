"""
Database persistence for Repository / Branch / AnalysisRun.

The one module allowed to write to these tables (matching the "one
module, one job" pattern used elsewhere -- e.g. github_client.py is the
only HTTP caller, clone_service.py the only subprocess caller).

Re-ingesting an already-known repository is an idempotent upsert keyed on
the primary key (the provider's own repository id) -- never a raw
IntegrityError leaking past this module. State transitions reuse
ALLOWED_TRANSITIONS from app.domain.repository_context directly (not a
duplicated copy), so the DB layer can never drift out of sync with the
in-memory state machine's rules.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.domain.errors import InvalidStateTransitionError
from app.domain.models import BranchInfo, RepositoryMetadata
from app.domain.repository_context import ALLOWED_TRANSITIONS, IngestionStatus
from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.models.repository import Repository


def get_or_create_repository(
    session: Session, *, metadata: RepositoryMetadata, provider: str, source_url: str
) -> Repository:
    existing = session.get(Repository, metadata.repository_id)
    if existing is not None:
        existing.provider = provider
        existing.source_url = source_url
        existing.owner = metadata.owner
        existing.name = metadata.name
        existing.default_branch = metadata.default_branch
        existing.description = metadata.description
        existing.visibility = metadata.visibility
        existing.primary_language = metadata.primary_language
        existing.license_name = metadata.license_name
        existing.stargazers_count = metadata.stargazers_count
        existing.forks_count = metadata.forks_count
        existing.open_issues_count = metadata.open_issues_count
        existing.updated_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(existing)
        return existing

    repository = Repository(
        id=metadata.repository_id,
        provider=provider,
        source_url=source_url,
        owner=metadata.owner,
        name=metadata.name,
        default_branch=metadata.default_branch,
        description=metadata.description,
        visibility=metadata.visibility,
        primary_language=metadata.primary_language,
        license_name=metadata.license_name,
        stargazers_count=metadata.stargazers_count,
        forks_count=metadata.forks_count,
        open_issues_count=metadata.open_issues_count,
    )
    session.add(repository)
    session.commit()
    session.refresh(repository)
    return repository


def upsert_branches(session: Session, *, repository_id: str, branches: list[BranchInfo]) -> list[Branch]:
    existing_by_name = {
        branch.name: branch
        for branch in session.query(Branch).filter(Branch.repository_id == repository_id).all()
    }

    result: list[Branch] = []
    for info in branches:
        row = existing_by_name.get(info.name)
        if row is not None:
            row.head_commit_sha = info.head_commit_sha
            row.is_default = info.is_default
        else:
            row = Branch(
                repository_id=repository_id,
                name=info.name,
                head_commit_sha=info.head_commit_sha,
                is_default=info.is_default,
            )
            session.add(row)
        result.append(row)

    session.commit()
    for row in result:
        session.refresh(row)
    return result


def create_analysis_run(
    session: Session, *, repository_id: str, requested_branch: str | None
) -> AnalysisRun:
    run = AnalysisRun(
        repository_id=repository_id,
        requested_branch=requested_branch,
        status=IngestionStatus.PENDING.value,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def transition_analysis_run(
    session: Session, *, run: AnalysisRun, new_status: IngestionStatus, error: dict | None = None
) -> None:
    current = IngestionStatus(run.status)
    allowed = ALLOWED_TRANSITIONS[current]
    if new_status not in allowed:
        raise InvalidStateTransitionError(
            f"Cannot transition AnalysisRun {run.id} from {current.value} to {new_status.value}"
        )

    run.status = new_status.value
    run.updated_at = datetime.now(timezone.utc)
    if new_status is IngestionStatus.FAILED:
        run.last_error = error
    session.commit()
    session.refresh(run)


def set_analysis_run_branch(session: Session, *, run: AnalysisRun, branch_id: int) -> None:
    run.branch_id = branch_id
    session.commit()
    session.refresh(run)


def set_analysis_run_commit_sha(session: Session, *, run: AnalysisRun, commit_sha: str) -> None:
    run.commit_sha = commit_sha
    session.commit()
    session.refresh(run)


def set_analysis_run_scan_result(session: Session, *, run: AnalysisRun, scan_result: dict) -> None:
    run.scan_result = scan_result
    session.commit()
    session.refresh(run)


def reconcile_stuck_run(session: Session, *, run: AnalysisRun, settings) -> None:
    """Force a run that's been sitting in a non-terminal state longer than
    settings.stuck_run_timeout_seconds to FAILED. Safe to call on every
    poll: a no-op for terminal or recently-updated runs. Every non-terminal
    IngestionStatus has a direct edge to FAILED, so this never raises
    InvalidStateTransitionError for a genuinely stuck run."""
    current = IngestionStatus(run.status)
    if current in (IngestionStatus.READY, IngestionStatus.FAILED):
        return

    updated_at = run.updated_at
    if updated_at.tzinfo is None:
        # SQLite has no native timezone-aware storage; values written as
        # UTC round-trip as naive datetimes. Treat naive as UTC rather
        # than comparing aware-vs-naive (which raises TypeError).
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age_seconds < settings.stuck_run_timeout_seconds:
        return

    transition_analysis_run(
        session,
        run=run,
        new_status=IngestionStatus.FAILED,
        error={
            "code": "STUCK_RUN_TIMEOUT",
            "message": f"AnalysisRun {run.id} made no progress for over {settings.stuck_run_timeout_seconds}s",
        },
    )
