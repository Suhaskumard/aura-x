"""
Phase 8: RepositoryContext assembly -- scanning, language/test-framework
detection, commit-history enrichment, and evolution-signal computation
wired together by app/services/repository_service.py.

Uses a real on-disk fixture tree (no clone, no network) plus an in-memory
fake provider, matching the pattern already used by
tests/test_repository_service.py's StubProvider.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.domain.errors import RepositoryScanFailedError
from app.domain.models import (
    BranchInfo,
    CloneResult,
    CommitInfo,
    FileChange,
    RepositoryMetadata,
)
from app.domain.repository_context import IngestionStatus, RepositoryContext
from app.domain.repository_provider import RepositoryProvider
from app.services.repository_service import (
    assemble_repository_context,
    build_repository_profile,
    enrich_commit_history,
)


class FakeProvider(RepositoryProvider):
    name = "fake"

    def __init__(self, file_changes_by_sha: dict[str, list[FileChange]]):
        self._file_changes_by_sha = file_changes_by_sha
        self.fetch_calls: list[str] = []

    def fetch_metadata(self, owner, repo) -> RepositoryMetadata:
        raise NotImplementedError

    def list_branches(self, owner, repo) -> list[BranchInfo]:
        raise NotImplementedError

    def get_commit_history(self, owner, repo, branch, limit) -> list[CommitInfo]:
        raise NotImplementedError

    def get_languages(self, owner, repo) -> dict[str, int]:
        raise NotImplementedError

    def get_commit_file_changes(self, owner, repo, sha) -> list[FileChange]:
        self.fetch_calls.append(sha)
        return self._file_changes_by_sha.get(sha, [])

    def clone(self, owner, repo, branch, target_dir) -> CloneResult:
        raise NotImplementedError


def make_commit(sha: str, *, changed_files: list[FileChange] | None = None) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        parents=[],
        author_name="Ada Lovelace",
        author_email="ada@example.com",
        committed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        message=f"commit {sha}",
        changed_files=changed_files or [],
    )


def make_repo_tree(root) -> None:
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (root / "tests" / "conftest.py").write_text("", encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")


def make_context(**overrides) -> RepositoryContext:
    defaults = dict(
        repository_id="repo-1",
        provider="fake",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        repository_name="hello-world",
    )
    defaults.update(overrides)
    ctx = RepositoryContext(**defaults)
    ctx.transition_to(IngestionStatus.VALIDATING)
    ctx.transition_to(IngestionStatus.FETCHING_METADATA)
    ctx.transition_to(IngestionStatus.FETCHING_BRANCHES)
    ctx.transition_to(IngestionStatus.CLONING)
    return ctx


# ---- enrich_commit_history ----


def test_enrich_populates_changed_files_up_to_limit():
    provider = FakeProvider({"a": [FileChange(path="x.py", additions=1)]})
    commits = [make_commit("a"), make_commit("b")]

    enriched = enrich_commit_history(provider, "octocat", "hello-world", commits, limit=1)

    assert enriched[0].changed_files[0].path == "x.py"
    assert enriched[1].changed_files == []  # beyond the limit, left untouched
    assert provider.fetch_calls == ["a"]


def test_enrich_skips_commits_that_already_have_changed_files():
    provider = FakeProvider({})
    already_enriched = make_commit("a", changed_files=[FileChange(path="pre.py")])
    commits = [already_enriched]

    enriched = enrich_commit_history(provider, "octocat", "hello-world", commits, limit=5)

    assert enriched[0].changed_files[0].path == "pre.py"
    assert provider.fetch_calls == []  # never re-fetched


# ---- assemble_repository_context ----


def test_assemble_populates_context_and_transitions_to_ready(tmp_path):
    make_repo_tree(tmp_path)
    provider = FakeProvider({"c1": [FileChange(path="app/main.py", additions=5)]})
    context = make_context(
        local_path=str(tmp_path),
        git_history=[make_commit("c1")],
    )

    result = assemble_repository_context(context, provider=provider)

    assert result is context
    assert context.analysis_status == IngestionStatus.READY
    assert context.last_error is None
    assert any(f.relative_path == "app/main.py" for f in context.file_tree)
    assert "Python" in context.languages
    assert "pytest" in context.test_frameworks
    assert context.evolution_signals is not None
    assert context.evolution_signals.analyzed_commit_count == 1
    assert context.evolution_signals.file_churn[0].path == "app/main.py"


def test_assemble_fails_with_structured_error_when_no_local_path():
    provider = FakeProvider({})
    context = make_context(local_path=None, git_history=[])

    result = assemble_repository_context(context, provider=provider)

    assert result.analysis_status == IngestionStatus.FAILED
    assert result.last_error["code"] == RepositoryScanFailedError.code


def test_assemble_preserves_github_language_counts(tmp_path):
    make_repo_tree(tmp_path)
    provider = FakeProvider({})
    context = make_context(
        local_path=str(tmp_path),
        git_history=[],
        languages={"Python": 99999},
    )

    result = assemble_repository_context(context, provider=provider)

    assert result.languages["Python"] >= 99999


# ---- build_repository_profile ----


def test_build_repository_profile_contains_expected_sections(tmp_path):
    make_repo_tree(tmp_path)
    provider = FakeProvider({})
    context = make_context(local_path=str(tmp_path), git_history=[])
    assemble_repository_context(context, provider=provider)

    profile = build_repository_profile(context)

    assert profile["owner"] == "octocat"
    assert profile["repository_name"] == "hello-world"
    assert profile["status"] == "READY"
    assert "Python" in profile["languages"]
    assert "pytest" in profile["test_frameworks"]
    assert "fastapi" in profile["dependencies"]
    assert profile["file_inventory"]["total_files"] > 0
    assert profile["git_history_summary"]["commit_count"] == 0
    assert "local_path" not in profile
    assert "token" not in str(profile).lower()


def test_build_repository_profile_handles_missing_metadata_and_local_path():
    context = make_context(local_path=None)
    profile = build_repository_profile(context)

    assert profile["description"] is None
    assert profile["dependencies"] == []
    assert profile["file_inventory"]["total_files"] == 0
