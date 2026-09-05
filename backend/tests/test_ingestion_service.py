import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.domain.errors import (
    BranchNotFoundError,
    InvalidRepositoryUrlError,
    RepositoryNotFoundError,
    RepositoryTooLargeError,
)
from app.models.analysis_run import AnalysisRun
from app.models.repository import Repository
from app.services import clone_service
from app.services.github_provider import GitHubProvider
from app.services.ingestion_service import continue_ingestion, start_ingestion

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")

REPO_PAYLOAD = {
    "id": 999001,
    "name": "hello-world",
    "owner": {"login": "octocat"},
    "description": "test repo",
    "default_branch": "main",
    "private": False,
    "language": "Python",
    "topics": [],
    "license": None,
    "stargazers_count": 1,
    "forks_count": 0,
    "open_issues_count": 0,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2024-06-01T12:30:00Z",
}

BRANCHES_PAYLOAD = [{"name": "main", "commit": {"sha": "abc123"}}]
LANGUAGES_PAYLOAD = {"Python": 1234}


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo_dir)
    return repo_dir


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        workspace_root=tmp_path / "workspace",
        clone_timeout_seconds=30,
        github_max_retries=1,
        github_request_timeout_seconds=1.0,
    )


@pytest.fixture(autouse=True)
def _allow_local_file_transport_for_tests(monkeypatch):
    monkeypatch.setitem(clone_service._GIT_ENV_OVERRIDES, "GIT_ALLOW_PROTOCOL", "https:file")


@pytest.fixture
def db_session_for_ingestion(tmp_path, settings):
    from sqlalchemy.orm import sessionmaker

    import app.models  # noqa: F401
    from app.db.base import Base
    from app.db.session import create_db_engine

    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def session_factory_for_ingestion(db_session_for_ingestion):
    # continue_ingestion always opens its OWN session (matching
    # production, where it must never reuse a request-scoped one) --
    # give it a fresh sessionmaker bound to the same engine as the test's
    # db_session_for_ingestion fixture.
    from sqlalchemy.orm import sessionmaker

    engine = db_session_for_ingestion.get_bind()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def _redirect_clone_to_local_repo(monkeypatch, local_repo):
    def fake_clone(self, owner, repo, branch, target_dir):
        # Mirror the real GitHubProvider.clone(): use the provider
        # instance's own settings (self._settings), not a fixture closed
        # over at monkeypatch-setup time -- otherwise a test that passes
        # a different Settings object would silently have its clone-time
        # settings (e.g. max_repository_size_mb) ignored.
        return clone_service._clone_and_verify(
            clone_url=str(local_repo), branch=branch, target_dir=Path(target_dir), settings=self._settings
        )

    monkeypatch.setattr(GitHubProvider, "clone", fake_clone)


def _mock_github(*, metadata=True, branches=True, languages=True):
    if metadata:
        respx.get("https://api.github.com/repos/octocat/hello-world").mock(
            return_value=httpx.Response(200, json=REPO_PAYLOAD)
        )
    if branches:
        respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
            return_value=httpx.Response(200, json=BRANCHES_PAYLOAD)
        )
    if languages:
        respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
            return_value=httpx.Response(200, json=LANGUAGES_PAYLOAD)
        )


# --------------------------------------------------------------------------
# start_ingestion: the fast synchronous part
# --------------------------------------------------------------------------


@respx.mock
def test_start_ingestion_creates_repository_and_run_at_fetching_metadata(db_session_for_ingestion, settings):
    _mock_github()
    run, parsed = start_ingestion(
        db_session_for_ingestion,
        source_url="https://github.com/octocat/hello-world",
        requested_branch=None,
        settings=settings,
    )
    assert run.status == "FETCHING_METADATA"
    assert parsed.owner == "octocat"
    assert parsed.repository == "hello-world"

    repo = db_session_for_ingestion.get(Repository, run.repository_id)
    assert repo.owner == "octocat"
    assert repo.name == "hello-world"


def test_start_ingestion_invalid_url_raises_before_any_row_created(db_session_for_ingestion, settings):
    with pytest.raises(InvalidRepositoryUrlError):
        start_ingestion(
            db_session_for_ingestion, source_url="not a url", requested_branch=None, settings=settings
        )
    assert db_session_for_ingestion.query(Repository).count() == 0


@respx.mock
def test_start_ingestion_metadata_404_raises_no_row_created(db_session_for_ingestion, settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(RepositoryNotFoundError):
        start_ingestion(
            db_session_for_ingestion,
            source_url="https://github.com/octocat/hello-world",
            requested_branch=None,
            settings=settings,
        )
    assert db_session_for_ingestion.query(Repository).count() == 0


# --------------------------------------------------------------------------
# continue_ingestion: the slow part, run with its own fresh session
# --------------------------------------------------------------------------


@respx.mock
def test_continue_ingestion_happy_path_reaches_ready(
    db_session_for_ingestion, session_factory_for_ingestion, settings
):
    _mock_github()
    run, parsed = start_ingestion(
        db_session_for_ingestion,
        source_url="https://github.com/octocat/hello-world",
        requested_branch=None,
        settings=settings,
    )

    continue_ingestion(
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=None,
        settings=settings,
        session_factory=session_factory_for_ingestion,
    )

    db_session_for_ingestion.refresh(run)
    assert run.status == "READY"
    assert run.commit_sha is not None
    assert run.branch_id is not None
    assert run.scan_result is not None
    assert "app.py" in {f["relative_path"] for f in run.scan_result["file_tree"]}


@respx.mock
def test_continue_ingestion_branch_not_found_marks_run_failed(
    db_session_for_ingestion, session_factory_for_ingestion, settings
):
    _mock_github()
    run, parsed = start_ingestion(
        db_session_for_ingestion,
        source_url="https://github.com/octocat/hello-world",
        requested_branch="does-not-exist",
        settings=settings,
    )

    continue_ingestion(
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch="does-not-exist",
        settings=settings,
        session_factory=session_factory_for_ingestion,
    )

    db_session_for_ingestion.refresh(run)
    assert run.status == "FAILED"
    assert run.last_error["code"] == "BRANCH_NOT_FOUND"


@respx.mock
def test_continue_ingestion_oversized_clone_marks_run_failed(
    db_session_for_ingestion, session_factory_for_ingestion, settings, tmp_path
):
    _mock_github()
    run, parsed = start_ingestion(
        db_session_for_ingestion,
        source_url="https://github.com/octocat/hello-world",
        requested_branch=None,
        settings=settings,
    )

    tiny_settings = settings.model_copy(update={"max_repository_size_mb": 0})
    continue_ingestion(
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=None,
        settings=tiny_settings,
        session_factory=session_factory_for_ingestion,
    )

    db_session_for_ingestion.refresh(run)
    assert run.status == "FAILED"
    assert run.last_error["code"] == "REPOSITORY_TOO_LARGE"


def test_continue_ingestion_unknown_run_id_logs_and_returns_without_raising(
    session_factory_for_ingestion, settings
):
    # Should never raise -- a background task's exception is silently
    # dropped, so this must degrade gracefully (log + return).
    continue_ingestion(
        999999,
        owner="octocat",
        repo="hello-world",
        requested_branch=None,
        settings=settings,
        session_factory=session_factory_for_ingestion,
    )
