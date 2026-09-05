"""
Translates app.domain.errors.RepositoryIntegrationError subclasses into
HTTP responses. Registered once in app/main.py via
@app.exception_handler(RepositoryIntegrationError) so every route (not
just repository ingestion) gets consistent, structured error responses
-- never a raw exception or stack trace reaching a client.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.domain.errors import RepositoryIntegrationError

_STATUS_BY_CODE: dict[str, int] = {
    "INVALID_REPOSITORY_URL": 400,
    "UNSUPPORTED_REPOSITORY_PROVIDER": 400,
    "REPOSITORY_NOT_FOUND": 404,
    "BRANCH_NOT_FOUND": 404,
    "REPOSITORY_ACCESS_DENIED": 403,
    "RATE_LIMITED": 429,
    "TIMEOUT": 504,
    "UPSTREAM_UNAVAILABLE": 502,
    "CLONE_FAILED": 502,
    "MALFORMED_RESPONSE": 502,
    "REPOSITORY_TOO_LARGE": 413,
    "INVALID_STATE_TRANSITION": 409,
    "REPOSITORY_SCAN_FAILED": 500,
}

_DEFAULT_STATUS = 500


async def repository_integration_error_handler(
    request: Request, exc: RepositoryIntegrationError
) -> JSONResponse:
    status_code = _STATUS_BY_CODE.get(exc.code, _DEFAULT_STATUS)
    return JSONResponse(status_code=status_code, content={"error": exc.to_dict()})
