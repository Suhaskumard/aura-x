"""
Real, network-hitting integration tests against a live small public GitHub
repository. Skipped by default -- run with:

    pytest --run-network
    # or
    AURA_X_RUN_NETWORK_TESTS=1 pytest

Uses octocat/Hello-World: GitHub's own smallest well-known public demo
repository, intentionally tiny and stable.
"""

import pytest

from app.core.config import Settings
from app.services.github_provider import GitHubProvider
from app.services.repository_service import resolve_branch

OWNER = "octocat"
REPO = "Hello-World"


@pytest.fixture
def live_provider():
    settings = Settings()
    with GitHubProvider(settings=settings) as provider:
        yield provider


@pytest.mark.network
def test_fetch_real_metadata(live_provider):
    metadata = live_provider.fetch_metadata(OWNER, REPO)
    assert metadata.owner.lower() == OWNER.lower()
    assert metadata.name.lower() == REPO.lower()
    assert metadata.visibility == "public"
    assert metadata.default_branch


@pytest.mark.network
def test_list_real_branches_includes_default(live_provider):
    branches = live_provider.list_branches(OWNER, REPO)
    assert len(branches) > 0
    assert any(b.is_default for b in branches)
    assert all(b.head_commit_sha for b in branches)


@pytest.mark.network
def test_resolve_branch_against_real_repository(live_provider):
    branch = resolve_branch(live_provider, OWNER, REPO, None)
    assert branch.is_default is True
    assert branch.head_commit_sha


@pytest.mark.network
def test_get_real_commit_history_bounded(live_provider):
    branch = resolve_branch(live_provider, OWNER, REPO, None)
    commits = live_provider.get_commit_history(OWNER, REPO, branch.name, limit=5)
    assert 0 < len(commits) <= 5
    assert all(c.sha for c in commits)


@pytest.mark.network
def test_get_real_languages(live_provider):
    languages = live_provider.get_languages(OWNER, REPO)
    assert isinstance(languages, dict)
