import pytest

from app.domain.errors import (
    BranchNotFoundError,
    CloneFailedError,
    InvalidRepositoryUrlError,
    InvalidStateTransitionError,
    MalformedUpstreamResponseError,
    RateLimitExceededError,
    RepositoryAccessDeniedError,
    RepositoryIntegrationError,
    RepositoryNotFoundError,
    RepositoryTooLargeError,
    UnsupportedRepositoryProviderError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

ALL_SUBCLASSES = [
    (InvalidRepositoryUrlError, "INVALID_REPOSITORY_URL"),
    (UnsupportedRepositoryProviderError, "UNSUPPORTED_REPOSITORY_PROVIDER"),
    (RepositoryNotFoundError, "REPOSITORY_NOT_FOUND"),
    (RepositoryAccessDeniedError, "REPOSITORY_ACCESS_DENIED"),
    (BranchNotFoundError, "BRANCH_NOT_FOUND"),
    (RateLimitExceededError, "RATE_LIMITED"),
    (UpstreamTimeoutError, "TIMEOUT"),
    (UpstreamUnavailableError, "UPSTREAM_UNAVAILABLE"),
    (MalformedUpstreamResponseError, "MALFORMED_RESPONSE"),
    (CloneFailedError, "CLONE_FAILED"),
    (RepositoryTooLargeError, "REPOSITORY_TOO_LARGE"),
    (InvalidStateTransitionError, "INVALID_STATE_TRANSITION"),
]


@pytest.mark.parametrize("error_cls,expected_code", ALL_SUBCLASSES)
def test_to_dict_shape_for_every_subclass(error_cls, expected_code):
    error = error_cls("something went wrong")
    assert error.to_dict() == {"code": expected_code, "message": "something went wrong"}


def test_base_error_default_code():
    error = RepositoryIntegrationError("base error")
    assert error.code == "REPOSITORY_INTEGRATION_ERROR"
    assert error.to_dict() == {"code": "REPOSITORY_INTEGRATION_ERROR", "message": "base error"}


def test_code_override_via_constructor_kwarg():
    error = RepositoryNotFoundError("custom", code="CUSTOM_CODE")
    assert error.code == "CUSTOM_CODE"
    assert error.to_dict()["code"] == "CUSTOM_CODE"


def test_exception_chaining_preserves_cause():
    original = ValueError("root cause")
    try:
        try:
            raise original
        except ValueError as exc:
            raise UpstreamUnavailableError("wrapped") from exc
    except UpstreamUnavailableError as wrapped:
        assert wrapped.__cause__ is original


def test_message_str_matches_exception_str():
    error = BranchNotFoundError("branch missing")
    assert str(error) == "branch missing"
    assert error.message == "branch missing"


def test_to_dict_does_not_leak_token_like_message_beyond_what_was_given():
    # Defense-in-depth: errors.py never fabricates extra content around the
    # message, so a caller who avoids putting a secret in the message string
    # can rely on to_dict() not introducing one.
    error = RepositoryAccessDeniedError("access denied")
    payload = error.to_dict()
    assert "token" not in payload["message"].lower()
    assert set(payload.keys()) == {"code", "message"}
