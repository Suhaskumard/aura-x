import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine, get_db
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}")
    engine = create_db_engine(settings)
    import app.models  # noqa: F401  (registers Repository/Branch/AnalysisRun)

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client_with_db(db_session: Session) -> TestClient:
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


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
