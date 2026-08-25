"""
Phase 16: verifies run_ingestion_job() genuinely hands off to the Phase
12 downstream analysis stages after a successful ingestion -- not a
mocked/skipped step -- and that a failure in that hand-off never affects
the (already-successful) ingestion outcome.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.core.config import Settings
from app.db.repository_dao import create_analysis_run, get_analysis_run, upsert_repository
from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileChange, RepositoryMetadata
from app.domain.repository_provider import RepositoryProvider, register_provider
from app.services.ingestion_orchestrator import run_ingestion_job

HOST = "handoff-provider.test"


def make_run(db_session, *, source_url: str) -> str:
    repository = upsert_repository(
        db_session, provider="handoff", owner="octocat", name="hello-world", source_url=source_url
    )
    run = create_analysis_run(
        db_session, repository, branch_name=None, commit_sha=None, config_snapshot={"evolution_commit_limit": 30}
    )
    db_session.commit()
    return run.id


class HandoffProvider(RepositoryProvider):
    name = "handoff"

    def __init__(self, settings=None):
        pass

    def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        return RepositoryMetadata(
            repository_id="1", name=repo, owner=owner, description=None,
            default_branch="main", visibility="public", primary_language="Python",
        )

    def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
        return [BranchInfo(name="main", head_commit_sha="sha1", is_default=True)]

    def get_commit_history(self, owner: str, repo: str, branch: str, limit: int) -> list[CommitInfo]:
        return [
            CommitInfo(
                sha="sha1", parents=[], author_name="Ada", author_email="ada@example.com",
                committed_at=datetime(2024, 1, 1, tzinfo=timezone.utc), message="init",
                changed_files=[FileChange(path="app/risky.py", additions=5)],
            )
        ]

    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        return {"Python": 100}

    def get_commit_file_changes(self, owner: str, repo: str, sha: str) -> list[FileChange]:
        return []

    def clone(self, owner: str, repo: str, branch: str, target_dir: str) -> CloneResult:
        os.makedirs(os.path.join(target_dir, "app"), exist_ok=True)
        with open(os.path.join(target_dir, "app", "risky.py"), "w", encoding="utf-8") as fh:
            fh.write("def unstable(): ...\n")
        return CloneResult(local_path=target_dir, commit_sha="sha1", branch=branch, cloned_at=datetime.now(timezone.utc))


def test_downstream_analysis_runs_and_logs_a_summary_after_ready(db_session, db_session_factory, tmp_path, caplog):
    register_provider(HOST, HandoffProvider)
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    caplog.set_level(logging.INFO, logger="app.services.ingestion_orchestrator")
    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    with db_session_factory() as session:
        run = get_analysis_run(session, run_id)
        assert run.status == "READY"

    summary_records = [r for r in caplog.records if "Downstream analysis complete" in r.getMessage()]
    assert len(summary_records) == 1
    message = summary_records[0].getMessage()
    assert "octocat/hello-world" in message
    assert "primary_language=Python" in message


def test_downstream_analysis_failure_does_not_affect_ingestion_outcome(
    db_session, db_session_factory, tmp_path, monkeypatch, caplog
):
    register_provider(HOST, HandoffProvider)
    run_id = make_run(db_session, source_url=f"https://{HOST}/octocat/hello-world")
    db_session.close()

    def boom(context):
        raise RuntimeError("simulated downstream analysis bug")

    monkeypatch.setattr("app.services.ingestion_orchestrator.run_downstream_analysis", boom)

    caplog.set_level(logging.INFO, logger="app.services.ingestion_orchestrator")
    run_ingestion_job(run_id, settings=Settings(workspace_root=tmp_path / "workspace"), session_factory=db_session_factory)

    with db_session_factory() as session:
        run = get_analysis_run(session, run_id)
        assert run.status == "READY"  # unaffected by the downstream failure
        assert run.result_profile is not None

    failure_records = [r for r in caplog.records if "Downstream analysis failed" in r.getMessage()]
    assert len(failure_records) == 1
