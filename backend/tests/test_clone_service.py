"""
Phase 7 (secure repository cloning) tests.

All tests clone from a real local git repository (built via subprocess
against tmp_path fixtures) -- no network, no GitHub dependency, but a real
`git clone` subprocess call for every case, matching the "don't mock the
shipped production path" rule.
"""

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.errors import CloneFailedError, RepositoryTooLargeError
from app.services import clone_service

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")


@pytest.fixture(autouse=True)
def _allow_local_file_transport_for_tests(monkeypatch):
    # Production clone_url is always validated https:// by _validate_clone_url
    # (tested in test_run_git_clone_rejects_non_https_urls). This only relaxes
    # git's own transport allowlist so these tests can clone from a local
    # filesystem fixture repo without needing real network access to
    # github.com -- GIT_ALLOW_PROTOCOL stays "https" in production.
    monkeypatch.setitem(clone_service._GIT_ENV_OVERRIDES, "GIT_ALLOW_PROTOCOL", "https:file")


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    """A real local git repo with one commit on 'main' and a 'feature' branch."""
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo_dir)
    _run(["git", "branch", "feature"], cwd=repo_dir)
    return repo_dir


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        clone_timeout_seconds=30,
        max_repository_size_mb=500,
    )


def _real_head_sha(repo_dir: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_clone_populates_correct_branch_and_head_sha(local_repo, settings):
    target_dir = settings.workspace_root / "repo-1" / "source"
    result = clone_service._clone_and_verify(
        clone_url=str(local_repo), branch="main", target_dir=target_dir, settings=settings
    )
    assert result.branch == "main"
    assert result.commit_sha == _real_head_sha(local_repo)
    assert (target_dir / "README.md").exists()
    assert (target_dir / ".git").exists()


def test_clone_specific_non_default_branch(local_repo, settings):
    target_dir = settings.workspace_root / "repo-2" / "source"
    result = clone_service._clone_and_verify(
        clone_url=str(local_repo), branch="feature", target_dir=target_dir, settings=settings
    )
    assert result.branch == "feature"
    assert result.commit_sha == _real_head_sha(local_repo)


def test_clone_repository_orchestration_entry_point(local_repo, settings):
    class FakeProvider:
        def clone(self, owner, repo, branch, target_dir):
            return clone_service._clone_and_verify(
                clone_url=str(local_repo),
                branch=branch,
                target_dir=Path(target_dir),
                settings=settings,
            )

    result = clone_service.clone_repository(
        provider=FakeProvider(),
        repository_id="repo-orch",
        owner="octocat",
        repo="hello-world",
        branch="main",
        settings=settings,
    )
    assert result.commit_sha == _real_head_sha(local_repo)
    assert "repo-orch" in result.local_path


# --------------------------------------------------------------------------
# workspace_dir_for security
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malicious_id",
    [
        "../../etc",
        "..",
        ".",
        "../escape",
        "/etc/passwd",
        "a/../../b",
        "repo\\..\\..\\escape",
        "",
        "a" * 300,
        "id;rm -rf /",
        "id\nrm -rf /",
    ],
)
def test_workspace_dir_for_rejects_malicious_repository_id(malicious_id, settings):
    with pytest.raises(CloneFailedError):
        clone_service.workspace_dir_for(malicious_id, settings)


def test_workspace_dir_for_accepts_safe_repository_id(settings):
    result = clone_service.workspace_dir_for("safe-repo-id_123", settings)
    assert result == (settings.workspace_root / "safe-repo-id_123" / "source").resolve()


def test_workspace_dir_never_escapes_workspace_root(settings):
    result = clone_service.workspace_dir_for("legit-id", settings)
    assert settings.workspace_root.resolve() in result.parents


# --------------------------------------------------------------------------
# branch / URL security
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malicious_branch",
    [
        "--upload-pack=touch /tmp/pwned",
        "-oProxyCommand=touch /tmp/pwned",
        "--help",
        "",
        "..",
        "branch;rm -rf /",
        "branch`rm -rf /`",
        "branch$(rm -rf /)",
        "branch\nrm -rf /",
        "branch\x00",
    ],
)
def test_run_git_clone_rejects_malicious_branch_names(malicious_branch, local_repo, settings):
    target_dir = settings.workspace_root / "repo-mal" / "source"
    with pytest.raises(CloneFailedError):
        clone_service._clone_and_verify(
            clone_url=str(local_repo),
            branch=malicious_branch,
            target_dir=target_dir,
            settings=settings,
        )
    assert not target_dir.exists()


@pytest.mark.parametrize(
    "bad_url",
    [
        "ext::sh -c touch /tmp/pwned",
        "file:///etc/passwd",
        "ssh://git@github.com/owner/repo.git",
        "git://github.com/owner/repo.git",
        "javascript:alert(1)",
    ],
)
def test_run_git_clone_rejects_non_https_urls(bad_url, settings):
    target_dir = settings.workspace_root / "repo-badurl" / "source"
    with pytest.raises(CloneFailedError):
        clone_service.run_git_clone(
            clone_url=bad_url, branch="main", target_dir=target_dir, settings=settings
        )
    assert not target_dir.exists()


# --------------------------------------------------------------------------
# Code-execution safety
# --------------------------------------------------------------------------


def test_clone_never_executes_repository_code(tmp_path, settings):
    repo_dir = tmp_path / "malicious_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)

    sentinel = tmp_path / "sentinel_should_not_exist.txt"
    # A setup.py that would leave evidence if it were ever executed.
    (repo_dir / "setup.py").write_text(
        f"open(r'{sentinel}', 'w').write('executed')\n", encoding="utf-8"
    )
    (repo_dir / "Makefile").write_text(
        f"all:\n\techo executed > {sentinel}\n", encoding="utf-8"
    )
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "malicious payload"], cwd=repo_dir)

    target_dir = settings.workspace_root / "repo-exec" / "source"
    clone_service._clone_and_verify(
        clone_url=str(repo_dir), branch="main", target_dir=target_dir, settings=settings
    )

    assert (target_dir / "setup.py").exists()  # file present
    assert not sentinel.exists()  # but never executed


# --------------------------------------------------------------------------
# Failure modes
# --------------------------------------------------------------------------


def test_clone_nonexistent_branch_raises_and_cleans_up(local_repo, settings):
    target_dir = settings.workspace_root / "repo-nobranch" / "source"
    with pytest.raises(CloneFailedError):
        clone_service._clone_and_verify(
            clone_url=str(local_repo),
            branch="does-not-exist",
            target_dir=target_dir,
            settings=settings,
        )
    assert not target_dir.exists()


def test_clone_empty_repository_raises(tmp_path, settings):
    repo_dir = tmp_path / "empty_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    # No commits at all -- "main" doesn't exist as a checkout-able ref yet.
    target_dir = settings.workspace_root / "repo-empty" / "source"
    with pytest.raises(CloneFailedError):
        clone_service._clone_and_verify(
            clone_url=str(repo_dir), branch="main", target_dir=target_dir, settings=settings
        )
    assert not target_dir.exists()


def test_clone_timeout_raises_clone_failed(local_repo, settings, monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(clone_service.subprocess, "run", fake_run)
    target_dir = settings.workspace_root / "repo-timeout" / "source"
    with pytest.raises(CloneFailedError):
        clone_service._clone_and_verify(
            clone_url=str(local_repo), branch="main", target_dir=target_dir, settings=settings
        )
    assert not target_dir.exists()


def test_clone_oversized_repository_raises_and_cleans_up(tmp_path, settings):
    repo_dir = tmp_path / "big_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))  # 2MB
    _run(["git", "add", "big.bin"], cwd=repo_dir)
    _run(["git", "commit", "-m", "big file"], cwd=repo_dir)

    tiny_settings = Settings(
        workspace_root=settings.workspace_root,
        clone_timeout_seconds=30,
        max_repository_size_mb=1,  # 1MB limit, repo is ~2MB
    )
    target_dir = tiny_settings.workspace_root / "repo-big" / "source"
    with pytest.raises(RepositoryTooLargeError):
        clone_service._clone_and_verify(
            clone_url=str(repo_dir), branch="main", target_dir=target_dir, settings=tiny_settings
        )
    assert not target_dir.exists()


def test_stale_workspace_directory_is_replaced(local_repo, settings):
    target_dir = settings.workspace_root / "repo-stale" / "source"
    target_dir.mkdir(parents=True)
    (target_dir / "leftover.txt").write_text("stale", encoding="utf-8")

    result = clone_service._clone_and_verify(
        clone_url=str(local_repo), branch="main", target_dir=target_dir, settings=settings
    )
    assert not (target_dir / "leftover.txt").exists()
    assert result.commit_sha == _real_head_sha(local_repo)


def test_git_executable_missing_raises_clone_failed(local_repo, settings, monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(clone_service.subprocess, "run", fake_run)
    target_dir = settings.workspace_root / "repo-nogit" / "source"
    with pytest.raises(CloneFailedError):
        clone_service._clone_and_verify(
            clone_url=str(local_repo), branch="main", target_dir=target_dir, settings=settings
        )


# --------------------------------------------------------------------------
# Phase 8 support: deepen_for_history / read_local_git_log
# --------------------------------------------------------------------------


def _cloned_repo(local_repo, settings, name="repo-deepen"):
    target_dir = settings.workspace_root / name / "source"
    clone_service._clone_and_verify(
        clone_url=str(local_repo), branch="main", target_dir=target_dir, settings=settings
    )
    return target_dir


def test_deepen_for_history_succeeds_on_real_clone(local_repo, settings):
    target_dir = _cloned_repo(local_repo, settings)
    clone_service.deepen_for_history(target_dir, settings)  # must not raise


def test_deepen_for_history_rejects_path_outside_workspace_root(local_repo, settings):
    # local_repo is a real, valid git repository that lives outside
    # settings.workspace_root -- without the containment check, `git
    # fetch --deepen` would happily succeed here (there's nothing to
    # deepen into since it has no remote, but it wouldn't fail on the
    # path check itself). This proves the check is load-bearing, not
    # just incidentally masked by "not a git repo" errors.
    with pytest.raises(CloneFailedError, match="outside workspace_root"):
        clone_service.deepen_for_history(local_repo, settings)


def test_read_local_git_log_returns_head_sha(local_repo, settings):
    target_dir = _cloned_repo(local_repo, settings)
    log = clone_service.read_local_git_log(target_dir, settings)
    assert _real_head_sha(local_repo) in log


def test_read_local_git_log_rejects_path_outside_workspace_root(tmp_path, settings):
    outside_dir = tmp_path / "not_in_workspace"
    outside_dir.mkdir()
    with pytest.raises(CloneFailedError):
        clone_service.read_local_git_log(outside_dir, settings)
