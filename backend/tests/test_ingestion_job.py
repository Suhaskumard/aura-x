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
from app.domain.errors import CloneFailedError, RepositoryIntegrationError
from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileChange, RepositoryMetadata
from app.domain.repository_context import IngestionStatus
from app.domain.repository_provider import RepositoryProvider, register_provider
from app.services import ingestion_orchestrator
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


# ---- Regression: the cloned workspace must not accumulate on disk forever ----
# Nothing reads context.local_path after run_ingestion_job() returns --
# file scanning, dependency/test-framework detection, and the Phase 16
# downstream-analysis hand-off all run synchronously inside this same
# call and their results are already captured in result_profile /
# logged. Leaving every ingestion's clone on disk is unbounded
# workspace_root growth with nothing to ever reclaim it.


def test_successful_ingestion_removes_the_cloned_workspace_from_disk(db_session, db_session_factory, tmp_path):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id))

    workspace_root = tmp_path / "workspace"
    run_ingestion_job(run_id, settings=Settings(workspace_root=workspace_root), session_factory=db_session_factory)

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "READY"  # cleanup happened after a genuinely successful run

    leftover = list(workspace_root.rglob("*")) if workspace_root.exists() else []
    assert leftover == [], f"cloned workspace was not cleaned up after ingestion: {leftover}"


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


# ---- Phase 16: hand-off to downstream analysis ----
# (log-message content and the "failure never affects ingestion" property
# are covered in tests/test_downstream_handoff.py; these two add what
# that file doesn't -- the exact RepositoryContext object handed off, and
# proof the hand-off never happens at all when ingestion itself fails.)


def test_downstream_analysis_runs_against_the_completed_context_on_success(
    db_session, db_session_factory, tmp_path, monkeypatch
):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id))

    calls = []
    real_run_downstream_analysis = ingestion_orchestrator.run_downstream_analysis

    def spy(context):
        calls.append(context)
        return real_run_downstream_analysis(context)

    monkeypatch.setattr(ingestion_orchestrator, "run_downstream_analysis", spy)

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    assert len(calls) == 1
    handed_off_context = calls[0]
    assert handed_off_context.analysis_status == IngestionStatus.READY
    assert handed_off_context.owner == "octocat"
    assert handed_off_context.repository_name == "hello-world"
    assert handed_off_context.commit_sha == "sha1"  # the real, resolved commit -- same one persisted

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "READY"  # unaffected by the hand-off


def test_downstream_analysis_not_run_when_ingestion_fails(db_session, db_session_factory, tmp_path, monkeypatch):
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id, fail_at="clone"))

    calls = []
    monkeypatch.setattr(ingestion_orchestrator, "run_downstream_analysis", lambda context: calls.append(context))

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    assert calls == []
    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "FAILED"


# ---- Regression: provider resolution/construction failure must not strand the run ----
# run_ingestion_job() used to resolve the provider class and construct the
# provider (`provider_cls(settings=settings)`) *before* entering the
# try/except that translates RepositoryIntegrationError into a FAILED run.
# A RepositoryIntegrationError raised at that point (e.g. the provider
# registered for this host became unavailable, or the provider's own
# constructor rejects the given settings) propagated straight out of
# run_ingestion_job uncaught -- as a background task, that's silently
# logged by the server and the AnalysisRun is left stuck at PENDING
# forever, exactly the "silent hang" this module's own docstring says
# must not happen.


class _ConstructorFailsProvider(RepositoryProvider):
    name = "ctor-fails"

    def __init__(self, settings=None):
        raise RepositoryIntegrationError("simulated: cannot construct provider", code="UPSTREAM_UNAVAILABLE")

    def fetch_metadata(self, owner, repo):  # pragma: no cover - never reached
        raise AssertionError("should never be called")

    def list_branches(self, owner, repo):  # pragma: no cover - never reached
        raise AssertionError("should never be called")

    def get_commit_history(self, owner, repo, branch, limit):  # pragma: no cover - never reached
        raise AssertionError("should never be called")

    def get_languages(self, owner, repo):  # pragma: no cover - never reached
        raise AssertionError("should never be called")

    def get_commit_file_changes(self, owner, repo, sha):  # pragma: no cover - never reached
        raise AssertionError("should never be called")

    def clone(self, owner, repo, branch, target_dir):  # pragma: no cover - never reached
        raise AssertionError("should never be called")


def test_provider_construction_failure_marks_run_failed_not_stuck(db_session, db_session_factory, tmp_path):
    ctor_fails_host = "ctor-fails-provider.test"
    register_provider(ctor_fails_host, _ConstructorFailsProvider)
    run_id = make_run(db_session, source_url=f"https://{ctor_fails_host}/octocat/hello-world")
    db_session.close()

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "FAILED"  # not stuck at PENDING
        assert final.error_code == "UPSTREAM_UNAVAILABLE"
        assert final.completed_at is not None


# ---- Regression: any unexpected exception mid-pipeline must not strand the run ----
# The pipeline's only exception handler used to catch just
# RepositoryIntegrationError. app/db/repository_dao.py's upsert_branches/
# upsert_commits do a check-then-insert against tables with a unique
# constraint (repository_id, name)/(repository_id, sha) with no locking --
# two overlapping run_ingestion_job calls for the same repository (e.g. a
# double-click on "refresh") can race and raise a raw
# sqlalchemy.exc.IntegrityError, which isn't a RepositoryIntegrationError
# and propagated straight out of run_ingestion_job uncaught, silently
# logged by the server with the run stuck forever instead of FAILED.


def test_unexpected_exception_mid_pipeline_marks_run_failed_not_stuck(
    db_session, db_session_factory, tmp_path, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    observed: list[tuple[str, str]] = []
    register_provider(HOST, make_recording_provider(db_session_factory, observed, run_id=run_id))

    def boom(db, repository, commits):
        raise IntegrityError(
            "simulated unique-constraint race between two concurrent runs",
            params=None,
            orig=Exception("UNIQUE constraint failed"),
        )

    monkeypatch.setattr(ingestion_orchestrator, "upsert_commits", boom)

    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    with db_session_factory() as session:
        final = get_analysis_run(session, run_id)
        assert final.status == "FAILED"  # not stuck at SCANNING
        assert final.error_code == "INTERNAL_ERROR"
        assert final.completed_at is not None
