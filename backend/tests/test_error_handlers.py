import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import repository_integration_error_handler
from app.domain import errors
from app.domain.errors import RepositoryIntegrationError

_EXPECTED_STATUS = {
    errors.InvalidRepositoryUrlError: 400,
    errors.UnsupportedRepositoryProviderError: 400,
    errors.RepositoryNotFoundError: 404,
    errors.BranchNotFoundError: 404,
    errors.RepositoryAccessDeniedError: 403,
    errors.RateLimitExceededError: 429,
    errors.UpstreamTimeoutError: 504,
    errors.UpstreamUnavailableError: 502,
    errors.CloneFailedError: 502,
    errors.MalformedUpstreamResponseError: 502,
    errors.RepositoryTooLargeError: 413,
    errors.InvalidStateTransitionError: 409,
    errors.RepositoryScanError: 500,
}


@pytest.fixture
def error_app() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(RepositoryIntegrationError, repository_integration_error_handler)

    @app.get("/boom/{code}")
    def boom(code: str):
        error_cls = next(cls for cls in _EXPECTED_STATUS if cls.code == code)
        raise error_cls("boom")

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("error_cls,expected_status", list(_EXPECTED_STATUS.items()))
def test_error_maps_to_expected_status(error_app, error_cls, expected_status):
    response = error_app.get(f"/boom/{error_cls.code}")
    assert response.status_code == expected_status
    body = response.json()
    assert body["error"]["code"] == error_cls.code
    assert body["error"]["message"] == "boom"


def test_base_error_maps_to_500_default():
    app = FastAPI()
    app.add_exception_handler(RepositoryIntegrationError, repository_integration_error_handler)

    @app.get("/boom")
    def boom():
        raise RepositoryIntegrationError("generic failure")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "REPOSITORY_INTEGRATION_ERROR"
