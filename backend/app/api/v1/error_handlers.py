"""
Structured-error -> HTTP response mapping (Phase 10).

Every app.domain.errors.RepositoryIntegrationError raised by a route
handler (directly, or by a service it calls) is caught here and turned
into a JSON body of exactly `exc.to_dict()` (`{"code": ..., "message":
...}`) with an appropriate status code -- never a raw exception, stack
trace, or FastAPI's default 500 body. This is the single place that
mapping lives, so a new error code only needs an entry added here.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import RepositoryIntegrationError

_STATUS_BY_CODE: dict[str, int] = {
    "INVALID_REPOSITORY_URL": 400,
    "UNSUPPORTED_REPOSITORY_PROVIDER": 400,
    "REPOSITORY_NOT_FOUND": 404,
    "REPOSITORY_ACCESS_DENIED": 403,
    "BRANCH_NOT_FOUND": 404,
    "RATE_LIMITED": 429,
    "TIMEOUT": 504,
    "UPSTREAM_UNAVAILABLE": 502,
    "MALFORMED_RESPONSE": 502,
    "CLONE_FAILED": 502,
    "REPOSITORY_TOO_LARGE": 413,
    "REPOSITORY_SCAN_FAILED": 500,
    "INVALID_STATE_TRANSITION": 500,
    "ANALYSIS_NOT_READY": 409,
    "UNAUTHORIZED": 401,
}

_DEFAULT_STATUS = 500


async def _repository_integration_error_handler(
    request: Request, exc: RepositoryIntegrationError
) -> JSONResponse:
    status_code = _STATUS_BY_CODE.get(exc.code, _DEFAULT_STATUS)
    return JSONResponse(status_code=status_code, content=exc.to_dict())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RepositoryIntegrationError, _repository_integration_error_handler)
