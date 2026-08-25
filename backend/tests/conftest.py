import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers ORM models on Base.metadata)
from app.db.base import Base
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session(tmp_path) -> Session:
    """A fresh, file-backed SQLite database per test -- no Postgres/Docker
    required. Same ORM models/constraints as production; only the engine
    dialect differs (see docs/GITHUB_INTEGRATION.md 'Database Persistence'
    for why the schema is written to be dialect-agnostic)."""
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


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
