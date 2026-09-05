import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import clone_service
from app.services.repository_scan_service import scan_repository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")


@pytest.fixture(autouse=True)
def _allow_local_file_transport_for_tests(monkeypatch):
    monkeypatch.setitem(clone_service._GIT_ENV_OVERRIDES, "GIT_ALLOW_PROTOCOL", "https:file")


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def source_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)

    (repo_dir / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (repo_dir / "requirements-dev.txt").write_text("pytest==8.0.0\n", encoding="utf-8")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo_dir)

    (repo_dir / "app.py").write_text("print('hello world')\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "update app"], cwd=repo_dir)

    return repo_dir


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "workspace", clone_timeout_seconds=30, scan_history_depth=10)


def test_scan_repository_end_to_end(source_repo, settings):
    target_dir = settings.workspace_root / "repo-scan" / "source"
    clone_service._clone_and_verify(
        clone_url=str(source_repo), branch="main", target_dir=target_dir, settings=settings
    )

    result = scan_repository(local_path=target_dir, github_languages={}, settings=settings)

    paths = {e.relative_path for e in result.file_tree}
    assert "app.py" in paths
    assert "tests/test_app.py" in paths

    assert result.languages.get("Python", 0) > 0
    assert "pytest" in result.test_frameworks
    assert result.evolution_signals.commits_analyzed >= 1


def test_scan_repository_prefers_github_languages_when_provided(source_repo, settings):
    target_dir = settings.workspace_root / "repo-scan-2" / "source"
    clone_service._clone_and_verify(
        clone_url=str(source_repo), branch="main", target_dir=target_dir, settings=settings
    )

    result = scan_repository(
        local_path=target_dir, github_languages={"Python": 99999}, settings=settings
    )
    assert result.languages == {"Python": 99999}
