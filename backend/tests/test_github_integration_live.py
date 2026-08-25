"""
Real, network-hitting integration tests against a live small public GitHub
repository. Skipped by default -- run with:

    pytest --run-network
    # or
    AURA_X_RUN_NETWORK_TESTS=1 pytest

Uses octocat/Hello-World: GitHub's own smallest well-known public demo
repository, intentionally tiny and stable.
"""

import shutil

import pytest

from app.core.config import Settings
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.services.file_scanner import scan_repository_tree
from app.services.github_provider import GitHubProvider
from app.services.language_detector import detect_languages
from app.services.repository_service import (
    assemble_repository_context,
    build_clone_target_dir,
    build_repository_profile,
    resolve_branch,
)

OWNER = "octocat"
REPO = "Hello-World"


@pytest.fixture
def live_settings(tmp_path):
    return Settings(workspace_root=tmp_path / "workspace")


@pytest.fixture
def live_provider(live_settings):
    with GitHubProvider(settings=live_settings) as provider:
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


@pytest.mark.network
def test_clone_real_repository(live_provider, live_settings):
    branch = resolve_branch(live_provider, OWNER, REPO, None)
    target_dir = build_clone_target_dir(live_settings, OWNER, REPO)

    from pathlib import Path

    try:
        result = live_provider.clone(OWNER, REPO, branch.name, target_dir)
        assert Path(result.local_path) == Path(target_dir).resolve()
        assert result.commit_sha
        assert result.branch == branch.name
        assert Path(result.local_path).is_dir()
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


@pytest.mark.network
def test_scan_real_cloned_repository_produces_nonempty_file_tree(live_provider, live_settings):
    branch = resolve_branch(live_provider, OWNER, REPO, None)
    target_dir = build_clone_target_dir(live_settings, OWNER, REPO)
    try:
        clone_result = live_provider.clone(OWNER, REPO, branch.name, target_dir)
        file_tree = scan_repository_tree(clone_result.local_path)
        assert len(file_tree) > 0

        # octocat/Hello-World is intentionally minimal (a single extensionless
        # README) so its language map can legitimately come back empty --
        # tests/test_language_detector.py covers the non-empty case with a
        # richer fixture tree; this just proves the real pipeline runs clean.
        languages = detect_languages(file_tree, live_provider.get_languages(OWNER, REPO))
        assert isinstance(languages, dict)
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


@pytest.mark.network
def test_assemble_repository_context_end_to_end_against_real_repository(live_provider, live_settings):
    branch = resolve_branch(live_provider, OWNER, REPO, None)
    metadata = live_provider.fetch_metadata(OWNER, REPO)
    commits = live_provider.get_commit_history(OWNER, REPO, branch.name, limit=5)
    target_dir = build_clone_target_dir(live_settings, OWNER, REPO)

    try:
        clone_result = live_provider.clone(OWNER, REPO, branch.name, target_dir)

        context = RepositoryContext(
            repository_id=metadata.repository_id,
            provider="github",
            source_url=f"https://github.com/{OWNER}/{REPO}",
            owner=OWNER,
            repository_name=REPO,
        )
        context.transition_to(IngestionStatus.VALIDATING)
        context.transition_to(IngestionStatus.FETCHING_METADATA)
        context.metadata = metadata
        context.transition_to(IngestionStatus.FETCHING_BRANCHES)
        context.selected_branch = branch.name
        context.default_branch = metadata.default_branch
        context.git_history = commits
        context.transition_to(IngestionStatus.CLONING)
        context.local_path = clone_result.local_path
        context.commit_sha = clone_result.commit_sha

        assemble_repository_context(context, provider=live_provider, evolution_commit_limit=5)

        assert context.analysis_status == IngestionStatus.READY
        assert context.file_tree
        assert context.evolution_signals is not None
        assert context.evolution_signals.analyzed_commit_count == len(commits)

        profile = build_repository_profile(context)
        assert profile["status"] == "READY"
        assert profile["file_inventory"]["total_files"] > 0
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
