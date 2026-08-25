"""
Phase 9: the persisted AnalysisRun.status state machine enforces the same
allow-list as the in-memory RepositoryContext (Phase 3) --
app.domain.repository_context.ALLOWED_TRANSITIONS.
"""

import pytest

from app.db.repository_dao import (
    complete_analysis_run,
    create_analysis_run,
    fail_analysis_run,
    transition_analysis_run,
    upsert_repository,
)
from app.domain.errors import InvalidStateTransitionError
from app.domain.repository_context import IngestionStatus


def make_run(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
    )
    return create_analysis_run(
        db_session, repository, branch_name="main", commit_sha=None, config_snapshot={}
    )


def test_new_run_starts_pending(db_session):
    run = make_run(db_session)
    assert run.status == IngestionStatus.PENDING.value
    assert run.completed_at is None


def test_valid_transition_sequence_is_accepted(db_session):
    run = make_run(db_session)
    sequence = [
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
        IngestionStatus.READY,
    ]
    for status in sequence:
        transition_analysis_run(db_session, run, status)
        assert run.status == status.value


def test_failed_reachable_from_any_non_terminal_state(db_session):
    for start in [
        IngestionStatus.PENDING,
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
    ]:
        run = make_run(db_session)
        run.status = start.value
        transition_analysis_run(db_session, run, IngestionStatus.FAILED)
        assert run.status == IngestionStatus.FAILED.value


def test_illegal_transition_is_rejected(db_session):
    run = make_run(db_session)
    with pytest.raises(InvalidStateTransitionError):
        transition_analysis_run(db_session, run, IngestionStatus.READY)  # cannot skip from PENDING
    assert run.status == IngestionStatus.PENDING.value  # unchanged


def test_terminal_states_reject_further_transitions(db_session):
    for terminal in [IngestionStatus.READY, IngestionStatus.FAILED]:
        run = make_run(db_session)
        run.status = terminal.value
        with pytest.raises(InvalidStateTransitionError):
            transition_analysis_run(db_session, run, IngestionStatus.VALIDATING)


def test_completed_at_set_on_ready_and_failed_only(db_session):
    run = make_run(db_session)
    transition_analysis_run(db_session, run, IngestionStatus.VALIDATING)
    assert run.completed_at is None
    transition_analysis_run(db_session, run, IngestionStatus.FETCHING_METADATA)
    transition_analysis_run(db_session, run, IngestionStatus.FETCHING_BRANCHES)
    transition_analysis_run(db_session, run, IngestionStatus.CLONING)
    transition_analysis_run(db_session, run, IngestionStatus.SCANNING)
    assert run.completed_at is None
    transition_analysis_run(db_session, run, IngestionStatus.READY)
    assert run.completed_at is not None


def test_complete_analysis_run_stores_profile_and_transitions_to_ready(db_session):
    run = make_run(db_session)
    for status in [
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
    ]:
        transition_analysis_run(db_session, run, status)

    complete_analysis_run(db_session, run, result_profile={"languages": {"Python": 100}})

    assert run.status == IngestionStatus.READY.value
    assert run.result_profile == {"languages": {"Python": 100}}


def test_fail_analysis_run_stores_structured_error(db_session):
    run = make_run(db_session)
    fail_analysis_run(db_session, run, {"code": "CLONE_FAILED", "message": "boom"})

    assert run.status == IngestionStatus.FAILED.value
    assert run.error_code == "CLONE_FAILED"
    assert run.error_message == "boom"
