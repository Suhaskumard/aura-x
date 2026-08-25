"""
Branch resolution: turn a user-supplied (owner, repo, branch?) into a
concrete, verified BranchInfo before anything downstream (clone, commit
history, analysis) proceeds.

This is provider-agnostic orchestration logic -- it only calls methods on
the RepositoryProvider interface, never a concrete provider directly, so
it works unchanged once GitLab/local providers exist.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

from app.core.config import Settings
from app.domain.errors import BranchNotFoundError, RepositoryIntegrationError, RepositoryScanFailedError
from app.domain.models import BranchInfo, CommitInfo, FileEntry
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import RepositoryProvider
from app.services.dependency_scanner import extract_dependencies
from app.services.evolution_analysis import compute_evolution_signals
from app.services.file_scanner import scan_repository_tree
from app.services.language_detector import detect_languages
from app.services.test_framework_detector import detect_test_directories, detect_test_frameworks


def resolve_branch(
    provider: RepositoryProvider, owner: str, repo: str, requested_branch: str | None
) -> BranchInfo:
    """Resolve the branch to analyze.

    If `requested_branch` is None, the repository's actual default branch
    is used. If a branch name is given, it must exist on the repository or
    BranchNotFoundError is raised -- callers must never silently fall back
    to a different branch than the one the user asked for.
    """
    branches = provider.list_branches(owner, repo)
    by_name = {branch.name: branch for branch in branches}

    if requested_branch is None:
        for branch in branches:
            if branch.is_default:
                return branch
        # Defensive fallback: list_branches() should always mark exactly
        # one branch as default (see GitHubProvider), but if a provider
        # implementation ever fails to, don't silently guess.
        raise BranchNotFoundError(
            f"Could not determine the default branch for {owner}/{repo}"
        )

    branch = by_name.get(requested_branch)
    if branch is None:
        raise BranchNotFoundError(
            f"Branch '{requested_branch}' does not exist on {owner}/{repo}"
        )
    return branch


def build_clone_target_dir(settings: Settings, owner: str, repo: str) -> str:
    """Build a fresh, unique clone workspace path under `settings.workspace_root`.

    Every call returns a distinct directory (even for the same repo) so
    concurrent or repeated ingestions of the same repository can never
    collide -- app/services/clone_service.py refuses to clone into a
    directory that already exists.
    """
    unique = uuid.uuid4().hex
    return str(Path(settings.workspace_root) / f"{owner}__{repo}__{unique}")


DEFAULT_EVOLUTION_COMMIT_LIMIT = 30


def enrich_commit_history(
    provider: RepositoryProvider,
    owner: str,
    repo: str,
    commits: list[CommitInfo],
    *,
    limit: int = DEFAULT_EVOLUTION_COMMIT_LIMIT,
) -> list[CommitInfo]:
    """Populate `changed_files` on up to `limit` of the most recent commits.

    GitHub's commit-list endpoint (used by get_commit_history, Phase 6)
    doesn't include per-file diffs -- only a single-commit fetch does. This
    is bounded to `limit` because it costs one extra API call per commit;
    commits beyond that window (or that already carry changed_files, e.g.
    from a stub/fixture) are passed through unchanged.
    """
    enriched: list[CommitInfo] = []
    for index, commit in enumerate(commits):
        if index >= limit or commit.changed_files:
            enriched.append(commit)
            continue
        changes = provider.get_commit_file_changes(owner, repo, commit.sha)
        enriched.append(replace(commit, changed_files=changes))
    return enriched


def assemble_repository_context(
    context: RepositoryContext,
    *,
    provider: RepositoryProvider,
    evolution_commit_limit: int = DEFAULT_EVOLUTION_COMMIT_LIMIT,
) -> RepositoryContext:
    """Turn a cloned RepositoryContext into a fully-populated one (Phase 8).

    Expects `context` to already be in CLONING with `local_path`,
    `metadata`, `branches`, and `git_history` populated by earlier
    ingestion steps (Phase 5/6/7). Scans the working tree, detects
    languages and test frameworks, computes evolution signals from commit
    history, and transitions SCANNING -> READY -- or -> FAILED with a
    structured error attached (`context.last_error`) on any failure.
    Mutates and returns `context`.
    """
    context.transition_to(IngestionStatus.SCANNING)
    try:
        if not context.local_path:
            raise RepositoryScanFailedError(
                f"RepositoryContext for {context.owner}/{context.repository_name} "
                "has no local_path to scan"
            )

        file_tree = scan_repository_tree(context.local_path)
        context.file_tree = file_tree
        context.languages = detect_languages(file_tree, context.languages)
        context.test_frameworks = detect_test_frameworks(context.local_path, file_tree)

        context.git_history = enrich_commit_history(
            provider,
            context.owner,
            context.repository_name,
            context.git_history,
            limit=evolution_commit_limit,
        )
        context.evolution_signals = compute_evolution_signals(context.git_history)

        context.transition_to(IngestionStatus.READY)
    except RepositoryIntegrationError as exc:
        context.fail(exc.to_dict())
    return context


def _count_by_category(file_tree: list[FileEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in file_tree:
        counts[entry.category] = counts.get(entry.category, 0) + 1
    return counts


def _most_recent_commit_at(commits: list[CommitInfo]) -> str | None:
    timestamps = [c.committed_at for c in commits if c.committed_at is not None]
    return max(timestamps).isoformat() if timestamps else None


def build_repository_profile(context: RepositoryContext) -> dict:
    """Curated, client-facing summary of a RepositoryContext -- identity,
    metadata, branch, commit SHA, languages, file inventory, test
    frameworks, dependencies, and a git history summary. Consumed by the
    /repositories API (Phase 10) and dashboard (Phase 12). Never includes
    the local filesystem path or a secret."""
    metadata = context.metadata
    file_tree = context.file_tree
    return {
        "repository_id": context.repository_id,
        "provider": context.provider,
        "owner": context.owner,
        "repository_name": context.repository_name,
        "source_url": context.source_url,
        "selected_branch": context.selected_branch,
        "default_branch": context.default_branch,
        "commit_sha": context.commit_sha,
        "status": context.analysis_status.value,
        "description": metadata.description if metadata else None,
        "visibility": metadata.visibility if metadata else None,
        "stargazers_count": metadata.stargazers_count if metadata else None,
        "forks_count": metadata.forks_count if metadata else None,
        "languages": context.languages,
        "test_frameworks": context.test_frameworks,
        "test_directories": detect_test_directories(file_tree),
        "dependencies": extract_dependencies(context.local_path) if context.local_path else [],
        "file_inventory": {
            "total_files": len(file_tree),
            "total_size_bytes": sum(entry.size_bytes for entry in file_tree),
            "by_category": _count_by_category(file_tree),
        },
        "git_history_summary": {
            "commit_count": len(context.git_history),
            "most_recent_commit_at": _most_recent_commit_at(context.git_history),
        },
        "updated_at": context.updated_at.isoformat(),
    }
