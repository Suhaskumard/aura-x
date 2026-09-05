from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine
from app.domain.errors import InvalidStateTransitionError
from app.domain.models import BranchInfo, RepositoryMetadata
from app.domain.repository_context import IngestionStatus
from app.models import AnalysisRun, Branch, Repository
from app.services.persistence_service import (
    create_analysis_run,
    get_or_create_repository,
    reconcile_stuck_run,
    set_analysis_run_scan_result,
    transition_analysis_run,
    upsert_branches,
)


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _metadata(**overrides) -> RepositoryMetadata:
    defaults = dict(
        repository_id="123456",
        name="hello-world",
        owner="octocat",
        description="desc",
        default_branch="main",
        visibility="public",
        primary_language="Python",
        stargazers_count=10,
    )
    defaults.update(overrides)
    return RepositoryMetadata(**defaults)


def test_get_or_create_repository_creates_new_row(db_session):
    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    assert repo.id == "123456"
    assert repo.owner == "octocat"

    fetched = db_session.get(Repository, "123456")
    assert fetched is not None


def test_get_or_create_repository_is_idempotent_upsert(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(stargazers_count=10), provider="github",
        source_url="https://github.com/octocat/hello-world",
    )
    get_or_create_repository(
        db_session, metadata=_metadata(stargazers_count=99), provider="github",
        source_url="https://github.com/octocat/hello-world",
    )

    all_rows = db_session.query(Repository).all()
    assert len(all_rows) == 1
    assert all_rows[0].stargazers_count == 99  # second call updated, not duplicated


def test_upsert_branches_creates_and_updates(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )

    upsert_branches(
        db_session,
        repository_id="123456",
        branches=[BranchInfo(name="main", head_commit_sha="abc", is_default=True)],
    )
    rows = db_session.query(Branch).filter(Branch.repository_id == "123456").all()
    assert len(rows) == 1
    assert rows[0].head_commit_sha == "abc"

    upsert_branches(
        db_session,
        repository_id="123456",
        branches=[BranchInfo(name="main", head_commit_sha="def", is_default=True)],
    )
    rows = db_session.query(Branch).filter(Branch.repository_id == "123456").all()
    assert len(rows) == 1  # updated in place, not duplicated
    assert rows[0].head_commit_sha == "def"


def test_create_analysis_run_starts_pending(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id="123456", requested_branch="main")
    assert run.status == "PENDING"
    assert run.branch_id is None


def test_transition_analysis_run_happy_path(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id="123456", requested_branch="main")

    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.VALIDATING)
    assert run.status == "VALIDATING"

    fetched = db_session.get(AnalysisRun, run.id)
    assert fetched.status == "VALIDATING"


def test_transition_analysis_run_illegal_jump_raises_and_leaves_status_unmutated(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id="123456", requested_branch="main")

    with pytest.raises(InvalidStateTransitionError):
        transition_analysis_run(db_session, run=run, new_status=IngestionStatus.READY)

    assert run.status == "PENDING"
    fetched = db_session.get(AnalysisRun, run.id)
    assert fetched.status == "PENDING"


def test_transition_analysis_run_failed_records_structured_error(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id="123456", requested_branch="main")

    error = {"code": "REPOSITORY_NOT_FOUND", "message": "not found"}
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.FAILED, error=error)

    assert run.status == "FAILED"
    assert run.last_error == error


def test_transition_analysis_run_from_terminal_state_raises(db_session):
    get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id="123456", requested_branch="main")
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.FAILED, error={"code": "X", "message": "y"})

    with pytest.raises(InvalidStateTransitionError):
        transition_analysis_run(db_session, run=run, new_status=IngestionStatus.VALIDATING)


def test_full_lineage_round_trip(db_session):
    # Matches Phase 9's own exit criteria: a completed ingestion is fully
    # persisted and re-readable with full repository/branch/run lineage.
    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    branches = upsert_branches(
        db_session,
        repository_id=repo.id,
        branches=[
            BranchInfo(name="main", head_commit_sha="abc", is_default=True),
            BranchInfo(name="dev", head_commit_sha="def", is_default=False),
        ],
    )
    main_branch = next(b for b in branches if b.name == "main")

    run = create_analysis_run(db_session, repository_id=repo.id, requested_branch="main")
    run.branch_id = main_branch.id
    run.commit_sha = "abc"
    db_session.commit()

    for status in [
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
        IngestionStatus.READY,
    ]:
        transition_analysis_run(db_session, run=run, new_status=status)

    db_session.expire_all()
    reloaded_repo = db_session.get(Repository, repo.id)
    reloaded_run = db_session.get(AnalysisRun, run.id)
    reloaded_branches = db_session.query(Branch).filter(Branch.repository_id == repo.id).all()

    assert reloaded_repo.owner == "octocat"
    assert {b.name for b in reloaded_branches} == {"main", "dev"}
    assert reloaded_run.status == "READY"
    assert reloaded_run.commit_sha == "abc"
    assert reloaded_run.branch_id == main_branch.id


# --------------------------------------------------------------------------
# reconcile_stuck_run
# --------------------------------------------------------------------------


def test_reconcile_stuck_run_forces_failed_when_stale(db_session):
    from datetime import datetime, timedelta, timezone

    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id=repo.id, requested_branch="main")
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.VALIDATING)
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.FETCHING_METADATA)
    run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=1000)
    db_session.commit()

    settings = Settings(stuck_run_timeout_seconds=600)
    reconcile_stuck_run(db_session, run=run, settings=settings)

    assert run.status == "FAILED"
    assert run.last_error["code"] == "STUCK_RUN_TIMEOUT"


def test_reconcile_stuck_run_leaves_fresh_run_untouched(db_session):
    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id=repo.id, requested_branch="main")
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.VALIDATING)

    settings = Settings(stuck_run_timeout_seconds=600)
    reconcile_stuck_run(db_session, run=run, settings=settings)

    assert run.status == "VALIDATING"
    assert run.last_error is None


def test_reconcile_stuck_run_leaves_terminal_run_untouched_even_if_stale(db_session):
    from datetime import datetime, timedelta, timezone

    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id=repo.id, requested_branch="main")
    transition_analysis_run(db_session, run=run, new_status=IngestionStatus.FAILED, error={"code": "X", "message": "y"})
    run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=100000)
    db_session.commit()

    settings = Settings(stuck_run_timeout_seconds=600)
    reconcile_stuck_run(db_session, run=run, settings=settings)  # must not raise

    assert run.status == "FAILED"
    assert run.last_error == {"code": "X", "message": "y"}  # untouched, not overwritten


def test_set_analysis_run_scan_result_round_trips(db_session):
    repo = get_or_create_repository(
        db_session, metadata=_metadata(), provider="github", source_url="https://github.com/octocat/hello-world"
    )
    run = create_analysis_run(db_session, repository_id=repo.id, requested_branch="main")

    payload = {"file_tree": [], "languages": {"Python": 1}, "test_frameworks": ["pytest"], "evolution_signals": {}}
    set_analysis_run_scan_result(db_session, run=run, scan_result=payload)

    assert run.scan_result == payload
    reloaded = db_session.get(type(run), run.id)
    assert reloaded.scan_result == payload
