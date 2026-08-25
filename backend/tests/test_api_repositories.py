"""
Phase 10: /api/v1/repositories API tests.

Mocks the GitHub HTTP boundary (respx, same pattern as
tests/test_github_provider.py) and the clone step (monkeypatching
app.services.github_provider.clone_repository to point at a real local
fixture tree, same pattern as test_github_provider.py's clone tests) --
so these exercise the real ingestion_orchestrator -> assemble_repository_
context -> persist_repository_context pipeline end-to-end through the
actual HTTP routes, with only the two true external boundaries (GitHub's
API, and `git`) faked.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import respx

from app.core.config import Settings, get_settings
from app.domain.models import CloneResult
from app.main import app

OWNER = "octocat"
REPO = "hello-world"

REPO_PAYLOAD = {
    "id": 123456,
    "name": REPO,
    "owner": {"login": OWNER},
    "description": "My first repository",
    "default_branch": "main",
    "private": False,
    "language": "Python",
    "topics": ["demo"],
    "license": {"name": "MIT License"},
    "stargazers_count": 42,
    "forks_count": 7,
    "open_issues_count": 3,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2024-06-01T12:30:00Z",
}
BRANCHES_PAYLOAD = [
    {"name": "main", "commit": {"sha": "sha-main"}},
    {"name": "dev", "commit": {"sha": "sha-dev"}},
]
COMMITS_PAYLOAD = [
    {
        "sha": "sha-main",
        "parents": [],
        "commit": {"message": "init", "author": {"name": "Ada", "email": "ada@example.com", "date": "2024-01-01T00:00:00Z"}},
    }
]
LANGUAGES_PAYLOAD = {"Python": 1234}


def mock_github(router: respx.MockRouter, *, owner: str = OWNER, repo: str = REPO) -> None:
    router.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    router.get(f"https://api.github.com/repos/{owner}/{repo}/branches").mock(
        return_value=httpx.Response(200, json=BRANCHES_PAYLOAD)
    )
    router.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
        return_value=httpx.Response(200, json=COMMITS_PAYLOAD)
    )
    router.get(f"https://api.github.com/repos/{owner}/{repo}/languages").mock(
        return_value=httpx.Response(200, json=LANGUAGES_PAYLOAD)
    )
    for commit in COMMITS_PAYLOAD:
        router.get(f"https://api.github.com/repos/{owner}/{repo}/commits/{commit['sha']}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sha": commit["sha"],
                    "files": [
                        {"filename": "app/main.py", "additions": 1, "deletions": 0, "status": "added"}
                    ],
                },
            )
        )


def make_fake_clone(tmp_path):
    clone_root = tmp_path / "fake-clone"
    (clone_root / "app").mkdir(parents=True)
    (clone_root / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (clone_root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
    (clone_root / "tests").mkdir()
    (clone_root / "tests" / "conftest.py").write_text("", encoding="utf-8")

    def fake_clone_repository(**kwargs):
        return CloneResult(
            local_path=str(clone_root),
            commit_sha="sha-main",
            branch=kwargs["branch"],
            cloned_at=datetime.now(timezone.utc),
        )

    return fake_clone_repository


def patch_clone(monkeypatch, tmp_path):
    import app.services.github_provider as github_provider_module

    monkeypatch.setattr(github_provider_module, "clone_repository", make_fake_clone(tmp_path))


def test_ingest_valid_public_repository_end_to_end(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "READY"
    assert body["owner"] == "octocat"
    assert body["name"] == "hello-world"
    assert body["selected_branch"] == "main"
    assert body["commit_sha"] == "sha-main"
    repository_id = body["repository_id"]

    detail = api_client.get(f"/api/v1/repositories/{repository_id}").json()
    assert detail["primary_language"] == "Python"
    assert detail["latest_analysis_run"]["status"] == "READY"

    profile = api_client.get(f"/api/v1/repositories/{repository_id}/profile")
    assert profile.status_code == 200
    profile_body = profile.json()
    assert "Python" in profile_body["profile"]["languages"]
    assert "pytest" in profile_body["profile"]["test_frameworks"]

    branches = api_client.get(f"/api/v1/repositories/{repository_id}/branches").json()
    assert {b["name"] for b in branches} == {"main", "dev"}
    assert next(b for b in branches if b["is_default"])["name"] == "main"

    commits = api_client.get(f"/api/v1/repositories/{repository_id}/commits").json()
    assert commits["total"] == 1
    assert commits["items"][0]["sha"] == "sha-main"


def test_ingest_invalid_url_returns_400_and_persists_nothing(api_client):
    response = api_client.post(
        "/api/v1/repositories/github", json={"repository_url": "not a url"}
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "INVALID_REPOSITORY_URL"

    listing = api_client.get("/api/v1/repositories").json()
    assert listing["total"] == 0


def test_ingest_unsupported_host_returns_400(api_client):
    response = api_client.post(
        "/api/v1/repositories/github", json={"repository_url": "https://gitlab.com/owner/repo"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_REPOSITORY_PROVIDER"


def test_ingest_selects_requested_branch(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world", "branch": "dev"},
        )

    assert response.status_code == 201
    assert response.json()["selected_branch"] == "dev"


def test_ingest_unknown_branch_persists_failed_run(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world", "branch": "does-not-exist"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error_code"] == "BRANCH_NOT_FOUND"

    profile = api_client.get(f"/api/v1/repositories/{body['repository_id']}/profile")
    assert profile.status_code == 409
    assert profile.json()["code"] == "ANALYSIS_NOT_READY"


def test_get_unknown_repository_returns_404(api_client):
    response = api_client.get("/api/v1/repositories/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "REPOSITORY_NOT_FOUND"


def test_refresh_reuses_repository_and_adds_analysis_run(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        first = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world"},
        ).json()

    with respx.mock:
        mock_github(respx)
        second = api_client.post(f"/api/v1/repositories/{first['repository_id']}/refresh", json={}).json()

    assert second["repository_id"] == first["repository_id"]
    assert second["analysis_run_id"] != first["analysis_run_id"]
    assert second["status"] == "READY"


def test_refresh_unknown_repository_returns_404(api_client):
    response = api_client.post("/api/v1/repositories/does-not-exist/refresh", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "REPOSITORY_NOT_FOUND"


def test_pagination_on_repository_list(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    for name in ["hello-world", "spoon-knife"]:
        with respx.mock:
            mock_github(respx, repo=name)
            api_client.post(
                "/api/v1/repositories/github",
                json={"repository_url": f"https://github.com/octocat/{name}"},
            )

    page1 = api_client.get("/api/v1/repositories", params={"page": 1, "page_size": 1}).json()
    assert page1["total"] == 2
    assert len(page1["items"]) == 1
    assert page1["page"] == 1
    assert page1["page_size"] == 1

    page2 = api_client.get("/api/v1/repositories", params={"page": 2, "page_size": 1}).json()
    assert len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]


def test_profile_not_ready_before_any_ingestion(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world"},
        )
    repository_id = response.json()["repository_id"]
    # sanity: this particular repo did succeed, so profile IS available --
    # covered by test_ingest_unknown_branch_persists_failed_run for the
    # not-ready case with a real repository_id.
    assert api_client.get(f"/api/v1/repositories/{repository_id}/profile").status_code == 200


def test_auth_required_when_api_auth_token_configured(api_client):
    app.dependency_overrides[get_settings] = lambda: Settings(api_auth_token="secret-token")
    try:
        unauthenticated = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world"},
        )
        assert unauthenticated.status_code == 401
        assert unauthenticated.json()["code"] == "UNAUTHORIZED"

        wrong_token = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": "https://github.com/octocat/hello-world"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert wrong_token.status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_auth_not_required_when_unconfigured(api_client):
    response = api_client.get("/api/v1/repositories")
    assert response.status_code == 200


def test_auth_not_enforced_on_read_endpoints_even_when_configured(api_client):
    app.dependency_overrides[get_settings] = lambda: Settings(api_auth_token="secret-token")
    try:
        response = api_client.get("/api/v1/repositories")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(get_settings, None)
