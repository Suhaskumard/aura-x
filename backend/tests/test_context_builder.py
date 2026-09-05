"""
Phase 12: downstream analysis hookup tests.

Proves build_repository_context() reconstructs a fully populated
RepositoryContext from persisted state alone, and that one commit SHA
flows unchanged through every hop that records it: GitHub's reported
branch-tip SHA (mocked here, but set to the real local repo's actual
HEAD SHA so the check is genuine) == the real git clone's rev-parse HEAD
== AnalysisRun.commit_sha == RepositoryContext.commit_sha.
"""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.domain.repository_context import IngestionStatus
from app.services import clone_service
from app.services.context_builder import build_repository_context, scan_result_to_dict
from app.services.github_provider import GitHubProvider
from app.services.ingestion_service import continue_ingestion, start_ingestion

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (repo_dir / "requirements.txt").write_text("pytest==8.0.0\n", encoding="utf-8")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo_dir)
    return repo_dir


@pytest.fixture
def real_head_sha(local_repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=local_repo)


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


@pytest.fixture(autouse=True)
def _redirect_clone_to_local_repo(monkeypatch, local_repo):
    def fake_clone(self, owner, repo, branch, target_dir):
        return clone_service._clone_and_verify(
            clone_url=str(local_repo), branch=branch, target_dir=Path(target_dir), settings=self._settings
        )

    monkeypatch.setattr(GitHubProvider, "clone", fake_clone)


@pytest.fixture
def db_session(tmp_path, settings):
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
def session_factory(db_session):
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, future=True)


def _mock_github(*, head_sha: str):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 999003,
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
            },
        )
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(200, json=[{"name": "main", "commit": {"sha": head_sha}}])
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, json={"Python": 1234})
    )


@respx.mock
def test_build_repository_context_matches_persisted_state(
    db_session, session_factory, settings, real_head_sha
):
    _mock_github(head_sha=real_head_sha)
    run, parsed = start_ingestion(
        db_session, source_url="https://github.com/octocat/hello-world", requested_branch=None, settings=settings
    )
    continue_ingestion(
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=None,
        settings=settings,
        session_factory=session_factory,
    )
    db_session.refresh(run)
    assert run.status == "READY"

    context = build_repository_context(db_session, run_id=run.id, settings=settings)

    assert context.repository_id == run.repository_id
    assert context.owner == "octocat"
    assert context.repository_name == "hello-world"
    assert context.provider == "github"
    assert context.selected_branch == "main"
    assert context.analysis_status == IngestionStatus.READY
    assert context.metadata.owner == "octocat"
    assert {b.name for b in context.branches} == {"main"}
    assert context.languages.get("Python") == 1234
    assert "pytest" in context.test_frameworks
    assert any(f.relative_path == "app.py" for f in context.file_tree)
    assert context.evolution_signals is not None
    assert context.evolution_signals.commits_analyzed >= 1
    assert context.local_path is not None


@respx.mock
def test_sha_consistency_across_every_hop(db_session, session_factory, settings, real_head_sha):
    _mock_github(head_sha=real_head_sha)
    run, parsed = start_ingestion(
        db_session, source_url="https://github.com/octocat/hello-world", requested_branch=None, settings=settings
    )
    continue_ingestion(
        run.id,
        owner=parsed.owner,
        repo=parsed.repository,
        requested_branch=None,
        settings=settings,
        session_factory=session_factory,
    )
    db_session.refresh(run)

    from app.models.branch import Branch

    branch_row = db_session.query(Branch).filter(Branch.repository_id == run.repository_id).one()
    context = build_repository_context(db_session, run_id=run.id, settings=settings)

    # GitHub's reported branch-tip SHA == real git clone's rev-parse HEAD
    # == persisted Branch.head_commit_sha == persisted AnalysisRun.commit_sha
    # == reconstructed RepositoryContext.commit_sha. All five must agree.
    assert real_head_sha == branch_row.head_commit_sha
    assert real_head_sha == run.commit_sha
    assert real_head_sha == context.commit_sha


def test_scan_result_to_dict_round_trips_evolution_signals_tuple_keys():
    from app.domain.models import EvolutionSignals, FileEntry
    from app.services.context_builder import _evolution_signals_from_dict, _file_tree_from_dicts
    from app.services.repository_scan_service import ScanResult

    signals = EvolutionSignals(
        commits_analyzed=3,
        file_churn={"a.py": 10, "b.py": 5},
        co_change_counts={("a.py", "b.py"): 2, ("b.py", "c.py"): 1},
    )
    scan_result = ScanResult(
        file_tree=[FileEntry(relative_path="a.py", extension=".py", size_bytes=10, category="source")],
        languages={"Python": 10},
        test_frameworks=["pytest"],
        evolution_signals=signals,
    )

    payload = scan_result_to_dict(scan_result)
    # Must be plain-JSON-safe: round-trip through json.dumps/loads.
    import json

    reloaded = json.loads(json.dumps(payload))

    restored_file_tree = _file_tree_from_dicts(reloaded["file_tree"])
    restored_signals = _evolution_signals_from_dict(reloaded["evolution_signals"])

    assert restored_file_tree == scan_result.file_tree
    assert restored_signals.co_change_counts == signals.co_change_counts
    assert restored_signals.file_churn == signals.file_churn
    assert restored_signals.commits_analyzed == 3


def test_build_repository_context_unknown_run_raises_not_found(db_session, settings):
    from app.domain.errors import RepositoryNotFoundError

    with pytest.raises(RepositoryNotFoundError):
        build_repository_context(db_session, run_id=999999, settings=settings)
