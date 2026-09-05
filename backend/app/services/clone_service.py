"""
Secure repository cloning.

This is the ONLY module in the codebase allowed to spawn a subprocess.
Every git invocation uses an argument list, never a shell string, so no
value derived from user input (owner, repo, branch, repository_id) can
ever be interpreted by a shell. See app/services/github_client.py for the
equivalent single-point-of-control pattern for the GitHub HTTP API.

Scope: public repositories only. A token is never used for cloning --
embedding one in an HTTPS clone URL would persist it in the cloned repo's
.git/config in plaintext, which the future Phase 8 filesystem scanner
would then read. A private-repo clone attempt fails with
RepositoryAccessDeniedError. Authenticated cloning is deferred; if added,
use `-c http.extraHeader` (not persisted to .git/config) paired with
`http.followRedirects=false`.

Concurrency: no locking exists between workspace_dir_for() and the
clone/rmtree calls below -- two concurrent clones of the same
repository_id can race. Safe today because nothing calls this
concurrently (Phase 11's async orchestrator doesn't exist yet); must be
addressed when that orchestrator is built.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.domain.errors import (
    CloneFailedError,
    RepositoryAccessDeniedError,
    RepositoryTooLargeError,
)
from app.domain.models import CloneResult

_SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
_RESERVED_SLUGS = frozenset({".", ".."})
_STDERR_TRUNCATE_LIMIT = 500

_GIT_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ALLOW_PROTOCOL": "https",
}


def _validate_slug(value: str, *, field_name: str) -> None:
    if not value or value in _RESERVED_SLUGS or not _SAFE_SLUG_RE.match(value):
        raise CloneFailedError(f"Unsafe {field_name} for workspace path: {value!r}")


def workspace_dir_for(repository_id: str, settings: Settings | None = None) -> Path:
    """Compute and validate the isolated workspace directory for a repository."""
    settings = settings or get_settings()
    _validate_slug(repository_id, field_name="repository_id")

    workspace_root = settings.workspace_root.resolve()
    candidate = (workspace_root / repository_id / "source").resolve()

    if candidate != workspace_root and workspace_root not in candidate.parents:
        raise CloneFailedError("Computed workspace path escaped workspace_root")

    return candidate


def _validate_local_path_within_workspace(target_dir: Path, settings: Settings) -> None:
    # These two entry points take a path argument directly (rather than a
    # repository_id routed through workspace_dir_for()), so re-check
    # containment the same way, defense in depth.
    workspace_root = settings.workspace_root.resolve()
    resolved = target_dir.resolve()
    if resolved != workspace_root and workspace_root not in resolved.parents:
        raise CloneFailedError("Path is outside workspace_root")


def deepen_for_history(target_dir: Path, settings: Settings | None = None) -> None:
    """Fetch additional local commit history beyond the shallow depth-1
    clone _clone_and_verify() produces, for Phase 8 evolution analysis.
    Idempotent past settings.scan_history_depth."""
    settings = settings or get_settings()
    _validate_local_path_within_workspace(target_dir, settings)
    try:
        _run_git(
            ["git", "fetch", "--deepen", str(settings.scan_history_depth)],
            cwd=target_dir,
            timeout=settings.clone_timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        raise CloneFailedError(f"git fetch --deepen failed: {_truncate(exc.stderr)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CloneFailedError(f"git fetch --deepen timed out after {settings.clone_timeout_seconds}s") from exc


def read_local_git_log(target_dir: Path, settings: Settings | None = None) -> str:
    """Return raw `git log --numstat` output (NUL-delimited per-commit
    blocks) for Phase 8 evolution analysis to parse."""
    settings = settings or get_settings()
    _validate_local_path_within_workspace(target_dir, settings)
    try:
        result = _run_git(
            ["git", "log", "--no-merges", "--numstat", "--pretty=format:%x00%H"],
            cwd=target_dir,
            timeout=settings.clone_timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        raise CloneFailedError(f"git log failed: {_truncate(exc.stderr)}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CloneFailedError(f"git log timed out after {settings.clone_timeout_seconds}s") from exc
    return result.stdout


def _validate_clone_url(clone_url: str) -> None:
    if not clone_url.startswith("https://"):
        raise CloneFailedError(f"Unsupported clone URL scheme: {clone_url!r}")


def _validate_branch_for_subprocess(branch: str) -> None:
    # Load-bearing, not defense-in-depth: "--branch <value>" consumes the
    # very next token as its argument before any "--" separator is ever
    # reached, so a branch name starting with "-" is a real git
    # argument-injection vector (e.g. "--upload-pack=...").
    if not branch or branch.startswith("-"):
        raise CloneFailedError(f"Unsafe branch name for clone: {branch!r}")
    if ".." in branch or "\x00" in branch:
        raise CloneFailedError(f"Unsafe branch name for clone: {branch!r}")
    if any(unicodedata.category(ch) == "Cc" for ch in branch):
        raise CloneFailedError(f"Branch name contains control characters: {branch!r}")


def _truncate(text: str | None, limit: int = _STDERR_TRUNCATE_LIMIT) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def _run_git(args: list[str], *, cwd: Path | None, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        timeout=timeout,
        text=True,
        env={**os.environ, **_GIT_ENV_OVERRIDES},
    )


def _enforce_size_limit(target_dir: Path, max_repository_size_mb: int) -> None:
    max_bytes = max_repository_size_mb * 1024 * 1024
    total_bytes = 0
    for entry in target_dir.rglob("*"):
        if entry.is_symlink() or not entry.is_file():
            continue
        total_bytes += entry.lstat().st_size
        if total_bytes > max_bytes:
            raise RepositoryTooLargeError(
                f"Cloned repository exceeds the {max_repository_size_mb}MB limit"
            )


def _read_head_sha(target_dir: Path, *, timeout: float) -> str:
    result = _run_git(["git", "rev-parse", "HEAD"], cwd=target_dir, timeout=timeout)
    return result.stdout.strip()


def _is_empty_working_tree(target_dir: Path) -> bool:
    return not any(entry.name != ".git" for entry in target_dir.iterdir())


def _force_rmtree(target_dir: Path) -> None:
    # git marks some files inside .git (notably pack files) read-only on
    # Windows; plain shutil.rmtree(..., ignore_errors=True) silently leaves
    # them (and the whole directory) behind instead of raising. Clear the
    # read-only bit on everything first so cleanup is actually reliable.
    if not target_dir.exists():
        return
    for root, dirs, files in os.walk(target_dir):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(target_dir, ignore_errors=True)


def run_git_clone(
    *, clone_url: str, branch: str, target_dir: Path, settings: Settings | None = None
) -> CloneResult:
    """Clone `clone_url` at `branch` into `target_dir` via argument-list
    subprocess calls only. Raises a structured app.domain.errors type on
    any failure and cleans up a partial workspace directory.

    Only https:// URLs are accepted -- this is the production entry point.
    Tests exercising real git subprocess behavior against a local
    filesystem repo (no network dependency) use `_clone_and_verify`
    directly, which skips only the URL-scheme gate and nothing else.
    """
    _validate_clone_url(clone_url)
    return _clone_and_verify(
        clone_url=clone_url, branch=branch, target_dir=target_dir, settings=settings
    )


def _clone_and_verify(
    *, clone_url: str, branch: str, target_dir: Path, settings: Settings | None = None
) -> CloneResult:
    settings = settings or get_settings()
    _validate_branch_for_subprocess(branch)

    if target_dir.exists():
        _force_rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    clone_args = [
        "git",
        "clone",
        "--branch",
        branch,
        "--single-branch",
        "--depth",
        "1",
        "--no-tags",
        "--",
        clone_url,
        str(target_dir),
    ]

    try:
        _run_git(clone_args, cwd=None, timeout=settings.clone_timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _force_rmtree(target_dir)
        raise CloneFailedError(
            f"Clone timed out after {settings.clone_timeout_seconds}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        _force_rmtree(target_dir)
        stderr = _truncate(exc.stderr)
        if "could not read Username" in stderr or "Authentication failed" in stderr:
            raise RepositoryAccessDeniedError(
                "GitHub access denied while cloning (private repository or insufficient scope)"
            ) from exc
        raise CloneFailedError(f"git clone failed: {stderr}") from exc
    except FileNotFoundError as exc:
        raise CloneFailedError("git executable not found on PATH") from exc

    try:
        _enforce_size_limit(target_dir, settings.max_repository_size_mb)
        commit_sha = _read_head_sha(target_dir, timeout=settings.clone_timeout_seconds)
        if _is_empty_working_tree(target_dir):
            raise CloneFailedError(f"Cloned repository '{clone_url}' has an empty working tree")
    except Exception:
        _force_rmtree(target_dir)
        raise

    return CloneResult(
        local_path=str(target_dir),
        commit_sha=commit_sha,
        branch=branch,
        cloned_at=datetime.now(timezone.utc),
    )


def clone_repository(
    *,
    provider,
    repository_id: str,
    owner: str,
    repo: str,
    branch: str,
    settings: Settings | None = None,
) -> CloneResult:
    """Top-level orchestration entry point: compute the safe workspace
    directory for `repository_id`, then delegate the actual clone
    operation to the given RepositoryProvider."""
    settings = settings or get_settings()
    target_dir = workspace_dir_for(repository_id, settings)
    return provider.clone(owner, repo, branch, str(target_dir))
