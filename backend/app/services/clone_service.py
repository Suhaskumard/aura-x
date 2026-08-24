"""
Secure repository cloning (Phase 7).

The only module allowed to invoke the `git` binary. Every clone:

- runs `git` as an explicit argument list (`shell=False` semantics --
  never a single interpolated command string), so no argument can smuggle
  a shell metacharacter or an extra command;
- is confined to a single, freshly-created directory inside
  `settings.workspace_root` -- `_validate_target_dir` rejects any target
  outside that root or that already exists, so one clone can never
  overwrite or read another's workspace;
- is shallow and single-branch (`--depth 1 --single-branch`), bounding
  both clone time and the amount of history fetched;
- is bounded by `settings.clone_timeout_seconds` (clone killed and
  workspace removed on timeout) and `settings.max_repository_size_mb`
  (workspace removed if the clone exceeds it);
- verifies the actually-cloned commit with `git rev-parse HEAD` rather
  than trusting a caller-supplied sha, since the remote's branch head can
  move between branch resolution and clone;
- never embeds a GitHub token in the clone URL or writes one into the
  cloned repository's `.git/config` -- an optional token is passed via a
  transient `-c http.extraheader=...` override that applies only to the
  clone invocation, and is stripped from any error message before it is
  raised.

Generic over the source: callers pass a ready-made `clone_url` (an
`https://` GitHub URL in production, a local path in tests), so this
module has no GitHub-specific knowledge and can be reused by any future
RepositoryProvider (GitLab, local).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings
from app.domain.errors import CloneFailedError, RepositoryTooLargeError
from app.domain.github_url import validate_owner_repo
from app.domain.models import CloneResult

# Conservative git ref-name allowlist: alphanumeric plus the separators
# real branch names use, must not start with '-' (would be parsed as a
# git flag) and must not contain '..' (ref-name spec forbids it too).
_BRANCH_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,243}[A-Za-z0-9])?$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _validate_branch(branch: str) -> str:
    if not branch or not isinstance(branch, str):
        raise CloneFailedError("Branch name must be a non-empty string")
    if ".." in branch or "\\" in branch or branch.startswith("-"):
        raise CloneFailedError(f"Invalid branch name: {branch!r}")
    if not _BRANCH_RE.match(branch):
        raise CloneFailedError(f"Invalid branch name: {branch!r}")
    return branch


def _validate_target_dir(target_dir: str, workspace_root: Path) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    resolved_root = workspace_root.resolve()
    resolved_target = Path(target_dir).resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise CloneFailedError(
            "Clone target directory must be inside the configured workspace root"
        )
    if resolved_target.exists():
        raise CloneFailedError(f"Clone target directory already exists: {resolved_target}")
    return resolved_target


def _redact(text: str, secret: str | None) -> str:
    if secret:
        text = text.replace(secret, "***")
    return text


def _force_remove_readonly(func, path, exc) -> None:
    # git leaves some files under .git read-only on Windows; a plain
    # rmtree() aborts on the first one (PermissionError) and leaves the
    # rest of the partial clone on disk. Clear the read-only bit and retry.
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def _safe_rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove_readonly)
    else:
        shutil.rmtree(path, onerror=_force_remove_readonly)


def _directory_size_bytes(path: Path) -> int:
    return sum(
        entry.stat().st_size
        for entry in path.rglob("*")
        if entry.is_file() and not entry.is_symlink()
    )


def clone_repository(
    *,
    clone_url: str,
    owner: str,
    repo: str,
    branch: str,
    target_dir: str,
    settings: Settings,
    token: str | None = None,
) -> CloneResult:
    """Clone `branch` of `clone_url` into `target_dir`.

    `target_dir` must resolve inside `settings.workspace_root` and must
    not already exist. Raises `CloneFailedError` on any validation
    failure, timeout, or non-zero `git` exit; raises
    `RepositoryTooLargeError` (and removes the partial clone) if the
    result exceeds `settings.max_repository_size_mb`.
    """
    validate_owner_repo(owner, repo)
    _validate_branch(branch)
    resolved_target = _validate_target_dir(target_dir, settings.workspace_root)

    args = ["git"]
    if token:
        # Process-scoped credential: applies only to this invocation and
        # is never written into the cloned repo's .git/config, unlike a
        # token embedded in the clone URL.
        args += ["-c", f"http.extraheader=AUTHORIZATION: bearer {token}"]
    args += [
        "clone",
        "--depth", "1",
        "--branch", branch,
        "--single-branch",
        "--no-tags",
        "--",
        clone_url,
        str(resolved_target),
    ]

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=settings.clone_timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        _safe_rmtree(resolved_target)
        raise CloneFailedError(
            f"Clone of {owner}/{repo}@{branch} exceeded "
            f"{settings.clone_timeout_seconds}s timeout"
        ) from None

    if result.returncode != 0:
        _safe_rmtree(resolved_target)
        stderr = _redact((result.stderr or "").strip(), token)
        raise CloneFailedError(f"git clone failed for {owner}/{repo}@{branch}: {stderr}")

    max_bytes = settings.max_repository_size_mb * 1024 * 1024
    size_bytes = _directory_size_bytes(resolved_target)
    if size_bytes > max_bytes:
        _safe_rmtree(resolved_target)
        raise RepositoryTooLargeError(
            f"{owner}/{repo}@{branch} is {size_bytes // (1024 * 1024)}MB, "
            f"exceeding the {settings.max_repository_size_mb}MB limit"
        )

    sha_result = subprocess.run(
        ["git", "-C", str(resolved_target), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=settings.clone_timeout_seconds,
        shell=False,
    )
    commit_sha = (sha_result.stdout or "").strip()
    if sha_result.returncode != 0 or not _SHA_RE.match(commit_sha):
        _safe_rmtree(resolved_target)
        raise CloneFailedError(f"Could not verify cloned commit for {owner}/{repo}@{branch}")

    return CloneResult(
        local_path=str(resolved_target),
        commit_sha=commit_sha,
        branch=branch,
        cloned_at=datetime.now(timezone.utc),
    )
