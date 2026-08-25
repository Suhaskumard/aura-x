"""
Repository (data-access) layer (Phase 9).

The single place services issue reads/writes for Repository/Branch/
Commit/AnalysisRun -- callers pass an explicit `Session` (from
app.db.session.get_db) rather than opening their own, and never
construct a query against these tables outside this module. This keeps
the persistence boundary in one place, matching the "no ad hoc queries"
requirement in docs/GITHUB_INTEGRATION.md.

The ingestion state machine persisted on AnalysisRun.status reuses
app.domain.repository_context.ALLOWED_TRANSITIONS -- the same allow-list
that governs the in-memory RepositoryContext (Phase 3) -- so a status
transition that would be illegal in memory is equally rejected here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import InvalidStateTransitionError
from app.domain.models import BranchInfo, CommitInfo, RepositoryMetadata
from app.domain.repository_context import ALLOWED_TRANSITIONS, IngestionStatus
from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.models.commit import Commit
from app.models.repository import Repository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---- Repository ----


def get_repository_by_id(db: Session, repository_id: str) -> Repository | None:
    return db.get(Repository, repository_id)


def get_repository_by_identity(db: Session, *, provider: str, owner: str, name: str) -> Repository | None:
    stmt = select(Repository).where(
        Repository.provider == provider, Repository.owner == owner, Repository.name == name
    )
    return db.execute(stmt).scalar_one_or_none()


def upsert_repository(
    db: Session,
    *,
    provider: str,
    owner: str,
    name: str,
    source_url: str,
    metadata: RepositoryMetadata | None = None,
    repository_id: str | None = None,
) -> Repository:
    """Create or update the Repository row for (provider, owner, name).

    Re-ingesting an already-known repository updates the existing row in
    place (fresh metadata, `updated_at` advanced) instead of creating a
    duplicate -- Branch/Commit/AnalysisRun history for it is preserved and
    extended, not reset.

    Two concurrent callers can both observe "no existing row" for the same
    brand-new identity and both attempt to insert -- the loser hits
    `uq_repositories_provider_owner_name` (see app/models/repository.py).
    Rather than let that raw IntegrityError surface as a 500 for what is a
    legitimate concurrent-request scenario (Phase 8), the loser rolls back
    its own failed insert and falls back to updating the row the winner
    just created, exactly as if it had observed it in the first place.
    """
    repository = get_repository_by_identity(db, provider=provider, owner=owner, name=name)
    if repository is None:
        repository = Repository(
            id=repository_id or str(uuid4()),
            provider=provider,
            owner=owner,
            name=name,
            source_url=source_url,
        )
        db.add(repository)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            repository = get_repository_by_identity(db, provider=provider, owner=owner, name=name)
            if repository is None:  # pragma: no cover - defensive; not actually a duplicate-insert race
                raise
            repository.source_url = source_url
    else:
        repository.source_url = source_url

    if metadata is not None:
        repository.provider_repository_id = metadata.repository_id
        repository.default_branch = metadata.default_branch
        repository.description = metadata.description
        repository.visibility = metadata.visibility
        repository.primary_language = metadata.primary_language
        repository.license_name = metadata.license_name
        repository.topics = list(metadata.topics)
        repository.stargazers_count = metadata.stargazers_count
        repository.forks_count = metadata.forks_count
        repository.open_issues_count = metadata.open_issues_count
        repository.remote_created_at = metadata.created_at
        repository.remote_updated_at = metadata.updated_at

    db.flush()
    return repository


# ---- Branch ----


def upsert_branches(db: Session, repository: Repository, branches: list[BranchInfo]) -> list[Branch]:
    """Replace the tracked branch set for `repository` with `branches`.

    Existing rows are updated in place (by name) to preserve their id;
    branches no longer reported by the provider are removed so the table
    reflects the repository's current branch list, not a historical log.
    """
    existing_by_name = {branch.name: branch for branch in repository.branches}
    seen_names: set[str] = set()

    for branch_info in branches:
        seen_names.add(branch_info.name)
        row = existing_by_name.get(branch_info.name)
        if row is None:
            row = Branch(repository_id=repository.id, name=branch_info.name)
            db.add(row)
            repository.branches.append(row)
        row.head_commit_sha = branch_info.head_commit_sha
        row.is_default = branch_info.is_default

    for name, row in list(existing_by_name.items()):
        if name not in seen_names:
            repository.branches.remove(row)
            db.delete(row)

    db.flush()
    return list(repository.branches)


# ---- Commit ----


def upsert_commits(db: Session, repository: Repository, commits: list[CommitInfo]) -> list[Commit]:
    """Upsert commit references (by sha) for `repository`. Never deletes --
    the commit history a prior analysis run looked at stays retrievable
    even if a later run fetches a shorter/different window."""
    existing_by_sha = {commit.sha: commit for commit in repository.commits}
    rows: list[Commit] = []

    for commit_info in commits:
        row = existing_by_sha.get(commit_info.sha)
        if row is None:
            row = Commit(repository_id=repository.id, sha=commit_info.sha)
            db.add(row)
            repository.commits.append(row)
        row.parents = list(commit_info.parents)
        row.author_name = commit_info.author_name
        row.author_email = commit_info.author_email
        row.committed_at = commit_info.committed_at
        row.message = commit_info.message
        row.additions = commit_info.additions
        row.deletions = commit_info.deletions
        row.changed_files = [
            {
                "path": change.path,
                "additions": change.additions,
                "deletions": change.deletions,
                "status": change.status,
            }
            for change in commit_info.changed_files
        ]
        rows.append(row)

    db.flush()
    return rows


# ---- AnalysisRun ----


def create_analysis_run(
    db: Session,
    repository: Repository,
    *,
    branch_name: str | None,
    commit_sha: str | None,
    config_snapshot: dict,
) -> AnalysisRun:
    run = AnalysisRun(
        repository_id=repository.id,
        branch_name=branch_name,
        commit_sha=commit_sha,
        config_snapshot=config_snapshot,
        status=IngestionStatus.PENDING.value,
    )
    db.add(run)
    db.flush()
    return run


def get_analysis_run(db: Session, run_id: str) -> AnalysisRun | None:
    return db.get(AnalysisRun, run_id)


def list_analysis_runs_for_repository(db: Session, repository_id: str) -> list[AnalysisRun]:
    stmt = (
        select(AnalysisRun)
        .where(AnalysisRun.repository_id == repository_id)
        .order_by(AnalysisRun.started_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def transition_analysis_run(db: Session, run: AnalysisRun, new_status: IngestionStatus) -> AnalysisRun:
    """Advance `run.status`, enforcing the same transition allow-list as
    the in-memory RepositoryContext state machine (Phase 3)."""
    current = IngestionStatus(run.status)
    allowed = ALLOWED_TRANSITIONS[current]
    if new_status not in allowed:
        raise InvalidStateTransitionError(
            f"Cannot transition AnalysisRun {run.id} from {current.value} to {new_status.value}"
        )
    run.status = new_status.value
    run.updated_at = _utcnow()
    if new_status in (IngestionStatus.READY, IngestionStatus.FAILED):
        run.completed_at = run.updated_at
    db.flush()
    return run


def complete_analysis_run(db: Session, run: AnalysisRun, *, result_profile: dict) -> AnalysisRun:
    transition_analysis_run(db, run, IngestionStatus.READY)
    run.result_profile = result_profile
    db.flush()
    return run


def fail_analysis_run(db: Session, run: AnalysisRun, error: dict) -> AnalysisRun:
    transition_analysis_run(db, run, IngestionStatus.FAILED)
    run.error_code = error.get("code")
    run.error_message = error.get("message")
    db.flush()
    return run


def get_latest_analysis_run(db: Session, repository_id: str) -> AnalysisRun | None:
    stmt = (
        select(AnalysisRun)
        .where(AnalysisRun.repository_id == repository_id)
        .order_by(AnalysisRun.started_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


# ---- Pagination (Phase 10: REST API layer) ----


def list_repositories(db: Session, *, offset: int, limit: int) -> list[Repository]:
    stmt = select(Repository).order_by(Repository.updated_at.desc()).offset(offset).limit(limit)
    return list(db.execute(stmt).scalars().all())


def count_repositories(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Repository)).scalar_one()


def list_commits(db: Session, repository_id: str, *, offset: int, limit: int) -> list[Commit]:
    stmt = (
        select(Commit)
        .where(Commit.repository_id == repository_id)
        .order_by(Commit.committed_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def count_commits(db: Session, repository_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(Commit).where(Commit.repository_id == repository_id)
    ).scalar_one()
