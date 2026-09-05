import pytest

from app.domain.errors import InvalidStateTransitionError
from app.domain.models import BranchInfo
from app.domain.repository_context import IngestionStatus, RepositoryContext


def make_context(**overrides) -> RepositoryContext:
    defaults = dict(
        repository_id="repo-123",
        provider="github",
        source_url="https://github.com/fastapi/fastapi",
        owner="fastapi",
        repository_name="fastapi",
    )
    defaults.update(overrides)
    return RepositoryContext(**defaults)


def test_default_status_is_pending():
    ctx = make_context()
    assert ctx.analysis_status == IngestionStatus.PENDING
    assert ctx.branches == []
    assert ctx.languages == {}
    assert ctx.last_error is None


def test_happy_path_transition_sequence():
    ctx = make_context()
    sequence = [
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
        IngestionStatus.READY,
    ]
    for status in sequence:
        ctx.transition_to(status)
        assert ctx.analysis_status == status


def test_failed_reachable_from_any_non_terminal_state():
    for start in [
        IngestionStatus.PENDING,
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
    ]:
        ctx = make_context()
        ctx.analysis_status = start
        ctx.transition_to(IngestionStatus.FAILED)
        assert ctx.analysis_status == IngestionStatus.FAILED


def test_illegal_transition_raises():
    ctx = make_context()
    with pytest.raises(InvalidStateTransitionError):
        ctx.transition_to(IngestionStatus.READY)  # cannot skip straight from PENDING


def test_terminal_states_have_no_outgoing_transitions():
    for terminal in [IngestionStatus.READY, IngestionStatus.FAILED]:
        ctx = make_context()
        ctx.analysis_status = terminal
        with pytest.raises(InvalidStateTransitionError):
            ctx.transition_to(IngestionStatus.VALIDATING)


def test_fail_sets_status_and_error_payload():
    ctx = make_context()
    error = {"code": "REPOSITORY_NOT_FOUND", "message": "not found"}
    ctx.fail(error)
    assert ctx.analysis_status == IngestionStatus.FAILED
    assert ctx.last_error == error


def test_updated_at_advances_on_transition():
    ctx = make_context()
    original_updated_at = ctx.updated_at
    ctx.transition_to(IngestionStatus.VALIDATING)
    assert ctx.updated_at >= original_updated_at


def test_to_dict_serializes_enum_as_plain_string():
    ctx = make_context(branches=[BranchInfo(name="main", head_commit_sha="abc123", is_default=True)])
    payload = ctx.to_dict()
    assert payload["analysis_status"] == "PENDING"
    assert isinstance(payload["analysis_status"], str)
    assert payload["branches"][0]["name"] == "main"


def test_context_never_carries_a_secret_field():
    ctx = make_context()
    payload = ctx.to_dict()
    forbidden_substrings = ("token", "secret", "password", "authorization")
    for key in payload:
        assert not any(s in key.lower() for s in forbidden_substrings)


@pytest.mark.parametrize("terminal", [IngestionStatus.READY, IngestionStatus.FAILED])
def test_fail_from_terminal_state_raises_instead_of_silently_succeeding(terminal):
    ctx = make_context()
    ctx.analysis_status = terminal
    with pytest.raises(InvalidStateTransitionError):
        ctx.fail({"code": "SOME_ERROR", "message": "boom"})
    # last_error must remain untouched since the transition never happened
    assert ctx.last_error is None


def test_allowed_transitions_every_non_terminal_state_can_eventually_reach_ready():
    from app.domain.repository_context import ALLOWED_TRANSITIONS

    def can_reach_ready(start: IngestionStatus, seen: set[IngestionStatus]) -> bool:
        if start == IngestionStatus.READY:
            return True
        if start in seen:
            return False
        seen.add(start)
        return any(can_reach_ready(nxt, seen) for nxt in ALLOWED_TRANSITIONS[start])

    for status in IngestionStatus:
        if status in (IngestionStatus.READY, IngestionStatus.FAILED):
            continue
        assert can_reach_ready(status, set()), f"{status} cannot reach READY"


def test_allowed_transitions_every_non_terminal_state_has_failed_edge():
    from app.domain.repository_context import ALLOWED_TRANSITIONS

    for status in IngestionStatus:
        if status in (IngestionStatus.READY, IngestionStatus.FAILED):
            continue
        assert IngestionStatus.FAILED in ALLOWED_TRANSITIONS[status], f"{status} missing FAILED edge"


def test_allowed_transitions_has_no_orphan_or_missing_states():
    from app.domain.repository_context import ALLOWED_TRANSITIONS

    assert set(ALLOWED_TRANSITIONS.keys()) == set(IngestionStatus)


def test_to_dict_datetime_fields_remain_datetime_objects_not_iso_strings():
    # Documented gap: to_dict() uses dataclasses.asdict(), which does not
    # stringify datetime fields. A caller passing this straight to
    # json.dumps() would get a TypeError. Captured explicitly so a future
    # JSON-safe serializer change is deliberate.
    ctx = make_context()
    payload = ctx.to_dict()
    assert isinstance(payload["created_at"], type(ctx.created_at))
    with pytest.raises(TypeError):
        import json

        json.dumps(payload)
