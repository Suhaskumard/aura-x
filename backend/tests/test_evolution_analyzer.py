import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import clone_service
from app.services.evolution_analyzer import _parse_numstat_log, analyze_evolution

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")


@pytest.fixture(autouse=True)
def _allow_local_file_transport_for_tests(monkeypatch):
    # Same rationale as tests/test_clone_service.py: production clone_url
    # is always https://, validated separately. This only relaxes git's
    # transport allowlist so these tests can use local filesystem repos.
    monkeypatch.setitem(clone_service._GIT_ENV_OVERRIDES, "GIT_ALLOW_PROTOCOL", "https:file")


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo_with_history(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "history_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)

    (repo_dir / "a.py").write_text("line1\n", encoding="utf-8")
    (repo_dir / "b.py").write_text("line1\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "commit 1: add a and b"], cwd=repo_dir)

    (repo_dir / "a.py").write_text("line1\nline2\n", encoding="utf-8")
    (repo_dir / "b.py").write_text("line1\nline2\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "commit 2: touch a and b together"], cwd=repo_dir)

    (repo_dir / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "commit 3: touch a alone"], cwd=repo_dir)

    return repo_dir


def test_parse_numstat_log_computes_churn_and_co_change():
    raw = (
        "\x00sha1\n2\t0\ta.py\n1\t0\tb.py\n"
        "\x00sha2\n1\t1\ta.py\n"
    )
    signals = _parse_numstat_log(raw)
    assert signals.commits_analyzed == 2
    assert signals.file_churn["a.py"] == 2 + 2  # 2+0 from sha1, 1+1 from sha2
    assert signals.file_churn["b.py"] == 1
    assert signals.co_change_counts[("a.py", "b.py")] == 1


def test_parse_numstat_log_handles_binary_files_without_crashing():
    raw = "\x00sha1\n-\t-\timage.png\n3\t1\tmain.py\n"
    signals = _parse_numstat_log(raw)
    assert signals.commits_analyzed == 1
    assert "image.png" not in signals.file_churn
    assert signals.file_churn["main.py"] == 4


def test_parse_numstat_log_caps_co_change_for_huge_commits():
    files = "\n".join(f"1\t0\tfile_{i}.py" for i in range(60))
    raw = f"\x00sha1\n{files}\n"
    signals = _parse_numstat_log(raw)
    assert signals.commits_analyzed == 1
    # churn still counted per file even though co-change pairing is skipped
    assert signals.file_churn["file_0.py"] == 1
    assert signals.co_change_counts == {}


def test_parse_numstat_log_empty_input():
    signals = _parse_numstat_log("")
    assert signals.commits_analyzed == 0
    assert signals.file_churn == {}
    assert signals.co_change_counts == {}


def test_analyze_evolution_against_real_local_repo(repo_with_history):
    settings = Settings(
        workspace_root=repo_with_history.parent / "workspace",
        clone_timeout_seconds=30,
        scan_history_depth=10,
    )
    # analyze_evolution runs clone_service.deepen_for_history(), which
    # requires the path to be inside workspace_root -- so clone into a
    # real workspace path first via a plain local clone, then analyze.
    target_dir = settings.workspace_root / "repo-evo" / "source"
    clone_service._clone_and_verify(
        clone_url=str(repo_with_history), branch="main", target_dir=target_dir, settings=settings
    )

    signals = analyze_evolution(target_dir, settings)
    assert signals.commits_analyzed >= 1
    assert "a.py" in signals.file_churn
