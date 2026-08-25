"""
Phase 11: run_ingestion_job() status-transition tests.

Registers a fake provider under a throwaway hostname so the pipeline can
be driven end-to-end without respx/HTTP mocking -- each provider method
records the AnalysisRun's *persisted* status, read back through a fresh
DB session, at the instant it's called. This directly proves transitions
happen live (each stage's real work only starts once the persisted
status already shows that stage, and only after the previous stage's
work has actually finished) rather than being replayed after the fact.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.db.repository_dao import create_analysis_run, get_analysis_run, upsert_repository
from app.domain.errors import CloneFailedError
from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileChange, RepositoryMetadata
from app.domain.repository_provider import RepositoryProvider, register_provider
from app.services.ingestion_orchestrator import run_ingestion_job

HOST = "recording-provider.test"


def make_run(db_session, *, source_url: str) -> str:
    repository = upsert_repository(
        db_session, provider="recording", owner="octocat", name="hello-world", source_url=source_url
    )
    run = create_analysis_run(
        db_session, repository, branch_name=None, commit_sha=None, config_snapshot={"evolution_commit_limit": 30}
    )
    db_session.commit()
    return run.id


def make_recording_provider(
    db_session_factory, observed: list[tuple[str, str]], *, run_id: str, fail_at: str | None = None
):
    """Build a RepositoryProvider subclass whose methods record the
    AnalysisRun's *persisted* status (read via a fresh session) at the
    instant each is called. `run_id` is captured by closure since
    run_ingestion_job always constructs the provider as
    `provider_cls(settings=settings)` -- there's no constructor slot to
    pass it through directly."""

    def _record(stage: str) -> None:
        with db_session_factory() as session:
            run = get_analysis_run(session, run_id)
            observed.append((stage, run.status))

    class RecordingProvider(RepositoryProvider):
        name = "recording"

        def __init__(self, settings=None):
            pass

        def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
            _record("fetch_metadata")
            if fail_at == "fetch_metadata":
                raise CloneFailedError("simulated failure during metadata fetch")
            return RepositoryMetadata(
                repository_id="1",
                name=repo,
                owner=owner,
                description=None,
                default_branch="main",
                visibility="public",
                primary_language="Python",
            )

        def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
            _record("list_branches")
            return [BranchInfo(name="main", head_commit_sha="sha1", is_default=True)]

        def get_commit_history(self, owner: str, repo: str, branch: str, limit: int) -> list[CommitInfo]:
            _record("get_commit_history")
            return [
                CommitInfo(
                    sha="sha1",
                    parents=[],
                    author_name="Ada",
                    author_email="ada@example.com",
                    committed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    message="init",
                    changed_files=[FileChange(path="app/main.py", additions=1)],
                )
            ]

        def get_languages(self, owner: str, repo: str) -> dict[str, int]:
            _record("get_languages")
            return {"Python": 100}

        def get_commit_file_changes(self, owner: str, repo: str, sha: str) -> list[FileChange]:
            return []

        def clone(self, owner: str, repo: str, branch: str, target_dir: str) -> CloneResult:
            _record("clone")
            if fail_at == "clone":
                raise CloneFailedError("simulated clone failure")
            import os

            os.makedirs(os.path.join(target_dir, "app"), exist_ok=True)
            with open(os.path.join(target_dir, "app", "main.py"), "w", encoding="utf-8") as fh:
                fh.write("print('hi')\n")
            return CloneResult(
                local_path=target_dir, commit_sha="sha1", branch=branch, cloned_at=datetime.now(timezone.utc)
            )

    return RecordingProvider


def test_status_transitions_occur_in_order_and_only_after_prior_work(db_session, db_session_factory, tmp_path):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()  # run_ingestion_job opens its own session

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id))

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    # Each stage's real work is only invoked once the run's *persisted*
    # status already reflects that it has started, and stages appear in
    # pipeline order -- not a replay after the fact.
    assert observed == [
        ("fetch_metadata", "FETCHING_METADATA"),
        ("list_branches", "FETCHING_BRANCHES"),
        ("get_commit_history", "FETCHING_BRANCHES"),
        ("get_languages", "FETCHING_BRANCHES"),
        ("clone", "CLONING"),
    ]

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "READY"
        assert final.completed_at is not None
        assert final.result_profile is not None


def test_failure_mid_pipeline_surfaces_failed_with_structured_error(db_session, db_session_factory, tmp_path):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id, fail_at="clone"))

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    # cloning was reached (not a silent hang before it) but never completed
    assert ("clone", "CLONING") in observed

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "FAILED"
        assert final.error_code == "CLONE_FAILED"
        assert final.error_message
        assert final.completed_at is not None
        assert final.result_profile is None


def test_failure_during_metadata_fetch_stops_before_cloning(db_session, db_session_factory, tmp_path):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(
        HOST, make_recording_provider(db_session_factory, observed, run_id=run_id, fail_at="fetch_metadata")
    )

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    assert observed == [("fetch_metadata", "FETCHING_METADATA")]  # never reached list_branches/clone

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "FAILED"
        assert final.error_code == "CLONE_FAILED"  # the simulated error's own code
