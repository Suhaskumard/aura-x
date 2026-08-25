"""
Structured error taxonomy for the GitHub/repository integration layer.

Every error that can reach an API response or a log line must be one of
these types (or wrap one). Raw exceptions from an HTTP client, git
subprocess, or database driver must be caught and translated into one of
these before crossing a module boundary — see docs/GITHUB_INTEGRATION.md
"Error handling".

None of these types may hold a secret value (token, credential-bearing
URL) in their message or attributes.
"""

from __future__ import annotations


class RepositoryIntegrationError(Exception):
    """Base class for all structured repository-integration errors."""

    code: str = "REPOSITORY_INTEGRATION_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class InvalidRepositoryUrlError(RepositoryIntegrationError):
    code = "INVALID_REPOSITORY_URL"


class UnsupportedRepositoryProviderError(RepositoryIntegrationError):
    code = "UNSUPPORTED_REPOSITORY_PROVIDER"


class RepositoryNotFoundError(RepositoryIntegrationError):
    code = "REPOSITORY_NOT_FOUND"


class RepositoryAccessDeniedError(RepositoryIntegrationError):
    code = "REPOSITORY_ACCESS_DENIED"


class BranchNotFoundError(RepositoryIntegrationError):
    code = "BRANCH_NOT_FOUND"


class RateLimitExceededError(RepositoryIntegrationError):
    code = "RATE_LIMITED"


class UpstreamTimeoutError(RepositoryIntegrationError):
    code = "TIMEOUT"


class UpstreamUnavailableError(RepositoryIntegrationError):
    code = "UPSTREAM_UNAVAILABLE"


class MalformedUpstreamResponseError(RepositoryIntegrationError):
    code = "MALFORMED_RESPONSE"


class CloneFailedError(RepositoryIntegrationError):
    code = "CLONE_FAILED"


class RepositoryTooLargeError(RepositoryIntegrationError):
    code = "REPOSITORY_TOO_LARGE"


class RepositoryScanFailedError(RepositoryIntegrationError):
    code = "REPOSITORY_SCAN_FAILED"


class InvalidStateTransitionError(RepositoryIntegrationError):
    code = "INVALID_STATE_TRANSITION"
