"""
Branch resolution: turn a user-supplied (owner, repo, branch?) into a
concrete, verified BranchInfo before anything downstream (clone, commit
history, analysis) proceeds.

This is provider-agnostic orchestration logic -- it only calls methods on
the RepositoryProvider interface, never a concrete provider directly, so
it works unchanged once GitLab/local providers exist.
"""

from __future__ import annotations

from app.domain.errors import BranchNotFoundError
from app.domain.models import BranchInfo
from app.domain.repository_provider import RepositoryProvider


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
