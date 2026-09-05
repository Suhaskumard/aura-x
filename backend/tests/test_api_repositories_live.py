"""
Real, network-hitting end-to-end test of the full ingestion pipeline
through the actual HTTP endpoint: URL -> real GitHub API -> real git
clone -> real scan -> real SQLite persistence. Skipped by default --
run with `pytest --run-network` or `AURA_X_RUN_NETWORK_TESTS=1 pytest`.

Uses octocat/Hello-World: GitHub's own smallest well-known public demo
repository, intentionally tiny and stable.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app


@pytest.fixture
def live_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'live_test.db'}",
        workspace_root=tmp_path / "workspace",
        clone_timeout_seconds=60,
    )


@pytest.fixture
def live_client_with_db(live_settings, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from app import models as _models  # noqa: F401  (registers ORM classes; avoid shadowing `app`)
    from app.db.base import Base
    from app.db.session import create_db_engine

    engine = create_db_engine(live_settings)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()

    get_settings.cache_clear()
    monkeypatch.setattr("app.services.ingestion_service.get_settings", lambda: live_settings)
    monkeypatch.setattr("app.api.v1.repositories.get_settings", lambda: live_settings)

    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        client = TestClient(app)
        client.db_session = session  # stashed for tests that need direct DB access
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        get_settings.cache_clear()


@pytest.mark.network
def test_full_ingestion_pipeline_against_real_public_repo(live_client_with_db, live_settings):
    response = live_client_with_db.post(
        "/api/v1/repositories", json={"source_url": "https://github.com/octocat/Hello-World"}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["repository"]["owner"].lower() == "octocat"
    # The response body reflects creation-time state (before the
    # background task runs), not the final outcome -- poll for that.
    assert body["analysis_run"]["status"] in {"PENDING", "VALIDATING", "FETCHING_METADATA"}

    repository_id = body["repository"]["id"]
    run_id = body["analysis_run"]["id"]

    # Starlette's TestClient runs BackgroundTasks synchronously to
    # completion before .post() returns, so the real ASGI-server case
    # (poll until READY) is simulated here with a single, immediate
    # status check rather than a real polling loop -- still exercises the
    # actual GET /analysis-runs/{id} endpoint against real persisted data.
    status_resp = live_client_with_db.get(f"/api/v1/analysis-runs/{run_id}")
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["status"] == "READY", status_body
    assert status_body["commit_sha"]

    profile_resp = live_client_with_db.get(f"/api/v1/repositories/{repository_id}")
    assert profile_resp.status_code == 200

    branches_resp = live_client_with_db.get(f"/api/v1/repositories/{repository_id}/branches")
    assert branches_resp.status_code == 200
    assert len(branches_resp.json()) > 0

    commits_resp = live_client_with_db.get(f"/api/v1/repositories/{repository_id}/commits")
    assert commits_resp.status_code == 200
    assert len(commits_resp.json()) > 0

    # Phase 12: the reconstructed RepositoryContext must agree with the
    # real API response for the same real repository.
    from app.services.context_builder import build_repository_context

    context = build_repository_context(live_client_with_db.db_session, run_id=run_id, settings=live_settings)
    assert context.commit_sha == status_body["commit_sha"]
    assert context.owner.lower() == "octocat"
    assert len(context.file_tree) > 0
    assert context.evolution_signals is not None
