"""
Phase 9: persist_repository_context() ties a fully-assembled
RepositoryContext (Phase 8) into the Repository/Branch/Commit/AnalysisRun
tables (Phase 9), reusing the same FakeProvider pattern as
tests/test_repository_context_assembly.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.db.repository_dao import get_repository_by_identity, list_analysis_runs_for_repository
from app.domain.models import (
    BranchInfo,
    CloneResult,
    CommitInfo,
    FileChange,
    RepositoryMetadata,
)
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import RepositoryProvider
from app.services.ingestion_persistence import build_config_snapshot, persist_repository_context
from app.services.repository_service import assemble_repository_context


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
        return []

    def clone(self, owner, repo, branch, target_dir) -> CloneResult:
        raise NotImplementedError


def make_commit(sha: str) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        parents=[],
        author_name="Ada Lovelace",
        author_email="ada@example.com",
        committed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        message=f"commit {sha}",
        changed_files=[FileChange(path="app/main.py", additions=1)],
    )


def make_repo_tree(root) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")


def make_ready_context(tmp_path) -> RepositoryContext:
    make_repo_tree(tmp_path)
    context = RepositoryContext(
        repository_id="ctx-1",
        provider="github",
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
        branches=[BranchInfo(name="main", head_commit_sha="sha1", is_default=True)],
        selected_branch="main",
        default_branch="main",
        commit_sha="sha1",
        git_history=[make_commit("sha1")],
    )
    context.transition_to(IngestionStatus.VALIDATING)
    context.transition_to(IngestionStatus.FETCHING_METADATA)
    context.transition_to(IngestionStatus.FETCHING_BRANCHES)
    context.transition_to(IngestionStatus.CLONING)
    context.local_path = str(tmp_path)
    return context


def test_persist_ready_context_writes_full_lineage(db_session, tmp_path):
    context = make_ready_context(tmp_path)
    provider = FakeProvider()
    assemble_repository_context(context, provider=provider)
    assert context.analysis_status == IngestionStatus.READY

    config_snapshot = build_config_snapshot(Settings(), evolution_commit_limit=30)
    run = persist_repository_context(db_session, context, config_snapshot=config_snapshot)

    assert run.status == IngestionStatus.READY.value
    assert run.branch_name == "main"
    assert run.commit_sha == "sha1"
    assert run.config_snapshot["max_commit_history"] == config_snapshot["max_commit_history"]
    assert "github_token" not in run.config_snapshot
    assert run.result_profile["languages"]
    assert run.result_profile["test_frameworks"] == context.test_frameworks

    repository = get_repository_by_identity(db_session, provider="github", owner="octocat", name="hello-world")
    assert repository is not None
    assert repository.branches[0].name == "main"
    assert repository.commits[0].sha == "sha1"
    assert [r.id for r in list_analysis_runs_for_repository(db_session, repository.id)] == [run.id]


def test_persist_failed_context_stores_structured_error(db_session, tmp_path):
    context = make_ready_context(tmp_path)
    context.local_path = None  # forces assemble_repository_context to fail
    provider = FakeProvider()
    assemble_repository_context(context, provider=provider)
    assert context.analysis_status == IngestionStatus.FAILED

    config_snapshot = build_config_snapshot(Settings(), evolution_commit_limit=30)
    run = persist_repository_context(db_session, context, config_snapshot=config_snapshot)

    assert run.status == IngestionStatus.FAILED.value
    assert run.error_code == "REPOSITORY_SCAN_FAILED"
    assert run.result_profile is None


def test_persist_reingestion_reuses_same_repository_row(db_session, tmp_path):
    context = make_ready_context(tmp_path)
    provider = FakeProvider()
    assemble_repository_context(context, provider=provider)
    config_snapshot = build_config_snapshot(Settings(), evolution_commit_limit=30)

    run1 = persist_repository_context(db_session, context, config_snapshot=config_snapshot)

    second_context = make_ready_context(tmp_path / "second-clone")
    second_context.repository_id = "ctx-2"  # a fresh in-memory ingestion of the same repo
    assemble_repository_context(second_context, provider=provider)
    run2 = persist_repository_context(db_session, second_context, config_snapshot=config_snapshot)

    assert run1.repository_id == run2.repository_id
    repository = get_repository_by_identity(db_session, provider="github", owner="octocat", name="hello-world")
    assert len(list_analysis_runs_for_repository(db_session, repository.id)) == 2
