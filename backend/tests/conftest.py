import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.network (make real calls to a live public GitHub repository).",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "network: test makes a real network call to a live public GitHub repository"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_network = config.getoption("--run-network") or os.environ.get("AURA_X_RUN_NETWORK_TESTS") == "1"
    if run_network:
        return
    skip_network = pytest.mark.skip(
        reason="network test skipped by default; pass --run-network or set AURA_X_RUN_NETWORK_TESTS=1"
    )
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
