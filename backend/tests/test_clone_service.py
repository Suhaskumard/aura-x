"""
Unit tests for app/services/clone_service.py. Clones from a local git
repository created on disk (via `git init`/`commit`) instead of the
network, so these run offline and fast while still exercising the real
`git` subprocess path.
"""

from __future__ import annotations

import subprocess

import pytest

from app.core.config import Settings
from app.domain.errors import CloneFailedError, RepositoryTooLargeError
from app.services import clone_service
from app.services.clone_service import clone_repository


def _run_git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def source_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _run_git("init", "--initial-branch=main", cwd=source)
    _run_git("config", "user.email", "test@example.com", cwd=source)
    _run_git("config", "user.name", "Test", cwd=source)
    (source / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git("add", "README.md", cwd=source)
    _run_git("commit", "-m", "initial commit", cwd=source)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    return source, head


@pytest.fixture
def settings(tmp_path):
    return Settings(
        workspace_root=tmp_path / "workspace",
        clone_timeout_seconds=30,
        max_repository_size_mb=500,
    )


def test_clone_creates_isolated_workspace_and_verifies_commit(source_repo, settings):
    source, expected_head = source_repo
    target_dir = settings.workspace_root / "acme__widgets__1"

    result = clone_repository(
        clone_url=str(source),
        owner="acme",
        repo="widgets",
        branch="main",
        target_dir=str(target_dir),
        settings=settings,
    )

    assert result.local_path == str(target_dir.resolve())
    assert result.commit_sha == expected_head
    assert result.branch == "main"
    assert (target_dir / "README.md").exists()
    assert result.cloned_at.tzinfo is not None


def test_clone_rejects_target_dir_outside_workspace_root(source_repo, settings, tmp_path):
    source, _ = source_repo
    outside = tmp_path / "elsewhere"

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="main",
            target_dir=str(outside),
            settings=settings,
        )
    assert not outside.exists()


def test_clone_rejects_target_dir_that_already_exists(source_repo, settings):
    source, _ = source_repo
    target_dir = settings.workspace_root / "already-there"
    target_dir.mkdir(parents=True)

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
        )


@pytest.mark.parametrize(
    "branch",
    ["-x", "--upload-pack=touch /tmp/pwned", "..", "has\\backslash", ""],
)
def test_clone_rejects_invalid_branch_names(source_repo, settings, branch):
    source, _ = source_repo
    target_dir = settings.workspace_root / "acme__widgets__bad-branch"

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch=branch,
            target_dir=str(target_dir),
            settings=settings,
        )
    assert not target_dir.exists()


def test_clone_rejects_invalid_owner_repo(source_repo, settings):
    source, _ = source_repo
    target_dir = settings.workspace_root / "bad-owner"

    with pytest.raises(Exception):
        clone_repository(
            clone_url=str(source),
            owner="-bad-owner",
            repo="widgets",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
        )


def test_clone_fails_for_nonexistent_branch(source_repo, settings):
    source, _ = source_repo
    target_dir = settings.workspace_root / "acme__widgets__missing-branch"

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="does-not-exist",
            target_dir=str(target_dir),
            settings=settings,
        )
    assert not target_dir.exists()


def test_clone_fails_cleanly_for_empty_repository(settings, tmp_path):
    # A repo with zero commits has no refs at all, so --branch <anything>
    # cannot resolve -- this is a distinct failure mode from "branch
    # doesn't exist on an otherwise-normal repo" (test_clone_fails_for_
    # nonexistent_branch above), worth its own coverage since git's
    # error path (and exit behavior) differs for a genuinely empty repo.
    empty_source = tmp_path / "empty-source"
    empty_source.mkdir()
    _run_git("init", "--initial-branch=main", cwd=empty_source)
    target_dir = settings.workspace_root / "acme__empty__1"

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(empty_source),
            owner="acme",
            repo="empty",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
        )
    assert not target_dir.exists()  # cleanup: no partial workspace left behind


def test_clone_checks_out_the_requested_non_default_branch(source_repo, settings):
    # All other clone tests only ever clone "main" -- this proves --branch
    # actually selects a *different* branch's content and commit, not just
    # accepting the argument without effect.
    source, main_head = source_repo
    _run_git("checkout", "-b", "feature", cwd=source)
    (source / "feature.txt").write_text("only on feature\n", encoding="utf-8")
    _run_git("add", "feature.txt", cwd=source)
    _run_git("commit", "-m", "feature commit", cwd=source)
    feature_head = subprocess.run(
        ["git", "rev-parse", "feature"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    target_dir = settings.workspace_root / "acme__widgets__feature"

    result = clone_repository(
        clone_url=str(source),
        owner="acme",
        repo="widgets",
        branch="feature",
        target_dir=str(target_dir),
        settings=settings,
    )

    assert result.branch == "feature"
    assert result.commit_sha == feature_head
    assert result.commit_sha != main_head
    assert (target_dir / "feature.txt").exists()
    assert (target_dir / "feature.txt").read_text(encoding="utf-8") == "only on feature\n"


def test_clone_enforces_size_limit_and_cleans_up(source_repo, settings):
    source, _ = source_repo
    settings.max_repository_size_mb = 0
    target_dir = settings.workspace_root / "acme__widgets__too-big"

    with pytest.raises(RepositoryTooLargeError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
        )
    assert not target_dir.exists()


def test_clone_timeout_cleans_up_workspace(source_repo, settings, monkeypatch):
    source, _ = source_repo
    target_dir = settings.workspace_root / "acme__widgets__timeout"

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(clone_service.subprocess, "run", fake_run)

    with pytest.raises(CloneFailedError):
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
        )
    assert not target_dir.exists()


def test_clone_failure_redacts_token_from_error(source_repo, settings, monkeypatch):
    source, _ = source_repo
    target_dir = settings.workspace_root / "acme__widgets__redact"
    secret = "supersecrettoken123"

    class FakeResult:
        returncode = 128
        stdout = ""
        stderr = f"fatal: could not authenticate with token {secret}"

    def fake_run(args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(clone_service.subprocess, "run", fake_run)

    with pytest.raises(CloneFailedError) as excinfo:
        clone_repository(
            clone_url=str(source),
            owner="acme",
            repo="widgets",
            branch="main",
            target_dir=str(target_dir),
            settings=settings,
            token=secret,
        )
    assert secret not in str(excinfo.value)
    assert not target_dir.exists()


def test_clone_does_not_write_token_into_cloned_repo_config(source_repo, settings):
    source, _ = source_repo
    target_dir = settings.workspace_root / "acme__widgets__no-token-leak"
    secret = "supersecrettoken123"

    clone_repository(
        clone_url=str(source),
        owner="acme",
        repo="widgets",
        branch="main",
        target_dir=str(target_dir),
        settings=settings,
        token=secret,
    )

    git_config = (target_dir / ".git" / "config").read_text(encoding="utf-8")
    assert secret not in git_config
