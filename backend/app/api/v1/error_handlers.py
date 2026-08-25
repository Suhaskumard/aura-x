"""
Structured-error -> HTTP response mapping (Phase 10).

Every app.domain.errors.RepositoryIntegrationError raised by a route
handler (directly, or by a service it calls) is caught here and turned
into a JSON body of exactly `exc.to_dict()` (`{"code": ..., "message":
...}`) with an appropriate status code -- never a raw exception, stack
trace, or FastAPI's default 500 body. This is the single place that
mapping lives, so a new error code only needs an entry added here.

A genuinely unexpected exception (a bug, not a translated
RepositoryIntegrationError) also gets a handler below: without one,
Starlette's own default returns a bare `text/plain "Internal Server
Error"` body, breaking every API client's assumption that error
responses are JSON `{"code": ..., "message": ...}`. The handler logs the
real exception server-side (never in the response, so nothing internal
-- a path, a query, a secret -- ever reaches the client) and returns a
generic 500 in the same shape as every other error.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import RepositoryIntegrationError

logger = logging.getLogger(__name__)

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


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=_DEFAULT_STATUS,
        content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RepositoryIntegrationError, _repository_integration_error_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
