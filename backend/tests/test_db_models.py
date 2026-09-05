from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine
from app.models import AnalysisRun, Branch, Repository


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _make_repository(**overrides) -> Repository:
    defaults = dict(
        id="123456",
        provider="github",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        name="hello-world",
        visibility="public",
    )
    defaults.update(overrides)
    return Repository(**defaults)


def test_tables_created(db_session):
    assert set(Base.metadata.tables.keys()) == {"repositories", "branches", "analysis_runs"}


def test_insert_and_read_repository(db_session):
    repo = _make_repository()
    db_session.add(repo)
    db_session.commit()

    fetched = db_session.get(Repository, "123456")
    assert fetched is not None
    assert fetched.owner == "octocat"
    assert fetched.stargazers_count == 0  # default applied


def test_duplicate_provider_owner_name_rejected(db_session):
    db_session.add(_make_repository(id="1"))
    db_session.commit()

    db_session.add(_make_repository(id="2"))  # same provider/owner/name, different PK
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_branch_name_per_repository_rejected(db_session):
    db_session.add(_make_repository())
    db_session.commit()

    db_session.add(Branch(repository_id="123456", name="main", head_commit_sha="abc"))
    db_session.commit()

    db_session.add(Branch(repository_id="123456", name="main", head_commit_sha="def"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_analysis_run_branch_id_nullable(db_session):
    db_session.add(_make_repository())
    db_session.commit()

    run = AnalysisRun(repository_id="123456", requested_branch="main")
    db_session.add(run)
    db_session.commit()

    assert run.branch_id is None
    assert run.status == "PENDING"


def test_cascade_delete_repository_removes_branches(db_session):
    db_session.add(_make_repository())
    db_session.commit()
    db_session.add(Branch(repository_id="123456", name="main", head_commit_sha="abc"))
    db_session.commit()

    repo = db_session.get(Repository, "123456")
    db_session.delete(repo)
    db_session.commit()

    remaining = db_session.query(Branch).filter(Branch.repository_id == "123456").all()
    assert remaining == []


def test_cascade_delete_repository_removes_analysis_runs(db_session):
    db_session.add(_make_repository())
    db_session.commit()
    db_session.add(AnalysisRun(repository_id="123456", requested_branch="main"))
    db_session.commit()

    repo = db_session.get(Repository, "123456")
    db_session.delete(repo)
    db_session.commit()

    remaining = db_session.query(AnalysisRun).filter(AnalysisRun.repository_id == "123456").all()
    assert remaining == []


def test_branch_deletion_sets_analysis_run_branch_id_null(db_session):
    db_session.add(_make_repository())
    db_session.commit()
    branch = Branch(repository_id="123456", name="main", head_commit_sha="abc")
    db_session.add(branch)
    db_session.commit()

    run = AnalysisRun(repository_id="123456", requested_branch="main", branch_id=branch.id)
    db_session.add(run)
    db_session.commit()

    db_session.delete(branch)
    db_session.commit()

    db_session.refresh(run)
    assert run.branch_id is None


def test_last_error_json_round_trip(db_session):
    db_session.add(_make_repository())
    db_session.commit()

    error_payload = {"code": "CLONE_FAILED", "message": "boom"}
    run = AnalysisRun(repository_id="123456", requested_branch="main", status="FAILED", last_error=error_payload)
    db_session.add(run)
    db_session.commit()

    fetched = db_session.get(AnalysisRun, run.id)
    assert fetched.last_error == error_payload


def test_create_db_engine_creates_missing_sqlite_parent_directory(tmp_path: Path):
    # Found live during Phase 16's real end-to-end walk: a fresh checkout
    # has no .workspace/ directory yet (it's gitignored), and sqlite3
    # never creates a missing parent directory itself -- it previously
    # surfaced as an opaque "unable to open database file"
    # OperationalError with no clue that the fix is just "create the
    # directory", for the very first request any real user ever makes.
    nested_missing_dir = tmp_path / "does" / "not" / "exist" / "yet"
    settings = Settings(database_url=f"sqlite:///{nested_missing_dir / 'test.db'}")

    assert not nested_missing_dir.exists()
    engine = create_db_engine(settings)
    assert nested_missing_dir.is_dir()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        session.add(_make_repository())
        session.commit()
    finally:
        session.close()
