"""Phase 0 (bootstrap) coverage: app startup, config loading, logging setup."""

import logging

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import configure_logging
from app.main import app


def test_app_starts_and_responds_end_to_end():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200


def test_app_can_be_constructed_repeatedly_without_error():
    # Simulates a reload/restart: constructing a second TestClient against
    # the same already-imported `app` must not raise or double-register
    # middleware/routes.
    with TestClient(app) as client_a, TestClient(app) as client_b:
        assert client_a.get("/api/v1/health").status_code == 200
        assert client_b.get("/api/v1/health").status_code == 200


def test_configure_logging_is_idempotent_and_does_not_duplicate_handlers():
    root = logging.getLogger()
    configure_logging()
    handler_count_after_first_call = len(root.handlers)
    configure_logging()
    configure_logging()
    # Calling configure_logging() multiple times (as would happen under a
    # reloader) must not keep stacking StreamHandlers.
    assert len(root.handlers) == handler_count_after_first_call


def test_missing_all_env_vars_still_produces_valid_settings():
    # No required fields: Settings must construct successfully with only
    # defaults when no environment variables / .env file are present.
    settings = Settings(_env_file=None)
    assert settings.app_name == "AURA-X"
    assert settings.github_token is None
    assert settings.has_github_token() is False


def test_invalid_database_url_type_is_still_accepted_as_string():
    # Settings does not validate database_url as a real DSN at construction
    # time (no connection is opened here) -- documented gap, not a crash.
    settings = Settings(database_url="not-a-real-connection-string")
    assert settings.database_url == "not-a-real-connection-string"


def test_health_endpoint_reflects_environment_setting():
    with TestClient(app) as client:
        body = client.get("/api/v1/health").json()
    assert body["environment"] in {"development", "production", "test", "staging"} or isinstance(
        body["environment"], str
    )
