import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (registers ORM models on Base.metadata)
from app.db.base import Base
from app.db.session import get_db, get_session_factory
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_engine(tmp_path):
    """A fresh, file-backed SQLite database per test -- no Postgres/Docker
    required. Same ORM models/constraints as production; only the engine
    dialect differs (see docs/GITHUB_INTEGRATION.md 'Database Persistence'
    for why the schema is written to be dialect-agnostic)."""
    engine = create_engine(f"sqlite:///{tmp_path}/test.db", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session_factory(db_engine) -> sessionmaker:
    """The sessionmaker itself, for code that opens its own Session outside
    a single fixture's lifetime -- e.g. Phase 11's run_ingestion_job, which
    runs as a background task with its own session (see
    app.db.session.get_session_factory)."""
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def db_session(db_session_factory) -> Session:
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(db_session, db_session_factory) -> TestClient:
    """TestClient for the real FastAPI app, with app.db.session.get_db and
    get_session_factory overridden to the per-test SQLite database -- so
    /api/v1 route tests (including their BackgroundTasks, which open their
    own session via get_session_factory) never touch the real (possibly
    unconfigured/unreachable) database Settings.database_url points at."""

    def _override_get_db():
        yield db_session

    def _override_get_session_factory() -> sessionmaker:
        return db_session_factory

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = _override_get_session_factory
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_session_factory, None)


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
