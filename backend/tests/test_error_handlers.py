"""
Regression: unhandled (non-RepositoryIntegrationError) exceptions must
still produce the API's standard JSON error shape.

app/api/v1/error_handlers.py used to register a handler only for
RepositoryIntegrationError. Any genuinely unexpected exception (a real
bug, an unanticipated DB error, ...) fell through to Starlette's own
default, which returns a bare `text/plain "Internal Server Error"` body
-- breaking every API client's assumption that an error response is JSON
`{"code": ..., "message": ...}` (the contract every other error path in
this API honors, see app/api/v1/error_handlers.py's own docstring). This
also means the real exception must still be observable server-side (via
logging), just never in the response.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from app.api.v1.routes import repositories as repositories_module
from app.main import app


def test_unhandled_exception_returns_standard_json_error_shape(monkeypatch, db_session, caplog):
    def boom(db, offset, limit):
        raise ValueError("boom - simulated unexpected internal bug")

    monkeypatch.setattr(repositories_module, "list_repositories", boom)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[repositories_module.get_db] = _override_get_db
    caplog.set_level(logging.ERROR)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/api/v1/repositories")
    finally:
        app.dependency_overrides.pop(repositories_module.get_db, None)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body == {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}
    # the real exception is still visible server-side, just never in the response
    assert "boom - simulated unexpected internal bug" not in response.text
    assert any("boom - simulated unexpected internal bug" in record.getMessage() for record in caplog.records) or any(
        record.exc_info and "boom - simulated unexpected internal bug" in str(record.exc_info[1]) for record in caplog.records
    )
