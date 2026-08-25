"""
Phase 12: integration test for the downstream analysis pipeline.

Builds one real, fully-assembled READY RepositoryContext (via Phase 8's
assemble_repository_context against a real on-disk fixture tree, same
pattern as tests/test_repository_context_assembly.py) and runs it through
run_downstream_analysis(), verifying:

  - the same repository_id/commit_sha appears, unchanged, on every one of
    the five reports (Repository/Branch/Commit selection stays consistent
    across every downstream stage for a single run -- this phase's second
    task), and
  - Evolution Analysis's report actually reflects the churn/co-change
    signals Phase 8 computed on the context (this phase's third task),
    not independently-recomputed or empty data, and
  - that data flows further downstream: the file Evolution flags as the
    hotspot is the same file Risk Assessment flags as high-risk and Test
    Planning recommends a test for.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.pipeline import run_downstream_analysis
from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileChange, RepositoryMetadata
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import RepositoryProvider
from app.services.repository_service import assemble_repository_context

BASE_TIME = datetime(2024, 3, 1, tzinfo=timezone.utc)


class FakeProvider(RepositoryProvider):
    name = "fake"

    def fetch_metadata(self, owner, repo) -> RepositoryMetadata:
        raise NotImplementedError

    def list_branches(self, owner, repo) -> list[BranchInfo]:
        raise NotImplementedError

    def get_commit_history(self, owner, repo, branch, limit) -> list[CommitInfo]:
        raise NotImplementedError

    def get_languages(self, owner, repo) -> dict[str, int]:
        raise NotImplementedError

    def get_commit_file_changes(self, owner, repo, sha) -> list[FileChange]:
        raise NotImplementedError  # every commit fixture below already carries changed_files

    def clone(self, owner, repo, branch, target_dir) -> CloneResult:
        raise NotImplementedError


def make_repo_tree(root) -> None:
    (root / "app").mkdir()
    (root / "app" / "risky.py").write_text("def unstable(): ...\n", encoding="utf-8")
    (root / "app" / "stable.py").write_text("def stable(): ...\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_stable.py").write_text("def test_stable(): pass\n", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")


def make_commit(sha: str, *, days_ago: int, changed_files: list[FileChange]) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        parents=[],
        author_name="Ada Lovelace",
        author_email="ada@example.com",
        committed_at=BASE_TIME - timedelta(days=days_ago),
        message=f"commit {sha}",
        changed_files=changed_files,
    )


@pytest.fixture
def ready_context(tmp_path) -> RepositoryContext:
    make_repo_tree(tmp_path)
    context = RepositoryContext(
        repository_id="repo-integration-1",
        provider="fake",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        repository_name="hello-world",
        metadata=RepositoryMetadata(
            repository_id="123456",
            name="hello-world",
            owner="octocat",
            description=None,
            default_branch="main",
            visibility="public",
            primary_language="Python",
        ),
        branches=[BranchInfo(name="main", head_commit_sha="sha3", is_default=True)],
        selected_branch="main",
        default_branch="main",
        commit_sha="sha3",
        git_history=[
            make_commit("sha1", days_ago=3, changed_files=[FileChange(path="app/risky.py", additions=3, deletions=1)]),
            make_commit("sha2", days_ago=2, changed_files=[FileChange(path="app/risky.py", additions=2, deletions=0)]),
            make_commit(
                "sha3",
                days_ago=0,
                changed_files=[
                    FileChange(path="app/risky.py", additions=1, deletions=1),
                    FileChange(path="app/stable.py", additions=1, deletions=0),
                ],
            ),
        ],
    )
    context.transition_to(IngestionStatus.VALIDATING)
    context.transition_to(IngestionStatus.FETCHING_METADATA)
    context.transition_to(IngestionStatus.FETCHING_BRANCHES)
    context.transition_to(IngestionStatus.CLONING)
    context.local_path = str(tmp_path)

    provider = FakeProvider()
    assemble_repository_context(context, provider=provider)
    assert context.analysis_status == IngestionStatus.READY
    return context


def test_repository_and_commit_selection_consistent_across_every_stage(ready_context):
    result = run_downstream_analysis(ready_context)

    for report in (
        result.intelligence,
        result.evolution,
        result.dependencies,
        result.risk,
        result.test_planning,
    ):
        assert report.repository_id == ready_context.repository_id == "repo-integration-1"
        assert report.commit_sha == ready_context.commit_sha == "sha3"

    assert result.repository_id == ready_context.repository_id
    assert result.commit_sha == ready_context.commit_sha


def test_evolution_analysis_consumes_phase_8_churn_signals(ready_context):
    result = run_downstream_analysis(ready_context)

    signals = ready_context.evolution_signals
    assert signals is not None
    assert signals.analyzed_commit_count == 3

    # Evolution's report is built directly from context.evolution_signals,
    # not recomputed or faked -- same hotspot, same churn count.
    assert result.evolution.analyzed_commit_count == signals.analyzed_commit_count
    assert [h.path for h in result.evolution.hotspot_files] == [s.path for s in signals.file_churn]
    top_hotspot = result.evolution.hotspot_files[0]
    assert top_hotspot.path == "app/risky.py"
    assert top_hotspot.change_count == 3  # touched in all three commits


def test_hotspot_flows_through_risk_and_test_planning(ready_context):
    result = run_downstream_analysis(ready_context)

    # app/risky.py: churned 3x, no associated test -- should surface as
    # high risk and get a concrete test recommendation.
    high_risk_paths = {item.path for item in result.risk.high_risk_files}
    assert "app/risky.py" in high_risk_paths

    recommended_paths = {rec.path for rec in result.test_planning.recommendations}
    assert "app/risky.py" in recommended_paths
    assert "pytest" in result.test_planning.detected_frameworks

    # app/stable.py: churned once, has a matching test file -- should not
    # be flagged as high risk.
    assert "app/stable.py" not in high_risk_paths


def test_dependency_analysis_reads_from_the_same_local_path(ready_context):
    result = run_downstream_analysis(ready_context)
    assert set(result.dependencies.dependencies) == {"fastapi", "pytest"}
    assert result.dependencies.ecosystems == ["Python"]


def test_repository_intelligence_reflects_the_same_file_tree(ready_context):
    result = run_downstream_analysis(ready_context)
    assert result.intelligence.total_files == len(ready_context.file_tree)
    assert result.intelligence.has_readme is True
    assert result.intelligence.has_test_directory is True


def test_run_downstream_analysis_rejects_non_ready_context():
    context = RepositoryContext(
        repository_id="repo-2",
        provider="fake",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        repository_name="hello-world",
    )
    with pytest.raises(ValueError):
        run_downstream_analysis(context)
