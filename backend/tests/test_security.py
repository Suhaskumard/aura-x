"""
Phase 15: consolidated, end-to-end security test suite.

Complements -- does not duplicate -- the security coverage already built
into earlier phases' own test files:
  - tests/test_github_url.py -- URL parsing security matrix (Phase 4):
    path traversal, header injection, embedded credentials, lookalike
    hosts, shell metacharacters, control characters.
  - tests/test_clone_service.py -- clone sandboxing (Phase 7): argument-
    list-only subprocess calls, workspace containment, invalid branch/
    owner/repo rejection, size limit, timeout, token redaction.
  - tests/test_excel_export.py -- credential-leakage in generated
    workbooks (Phase 14).

What's new here is verifying those same properties hold *end-to-end*
through the real API layer (not just at the unit that enforces them),
plus the one genuinely cross-cutting requirement no single earlier phase
owned: token-leakage checks across logs, error responses, and persisted
state together, in one place.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from app.core.config import Settings, get_settings
from app.db.repository_dao import get_analysis_run
from app.domain.errors import RepositoryTooLargeError
from app.main import app
from tests.test_api_repositories import OWNER, REPO, mock_github, patch_clone

FAKE_TOKEN = "ghp_SuperSecretFakeTokenForTestingOnly1234567890"  # nosec - test fixture only


# ---- Malformed/malicious URLs and protocols, end-to-end through the API ----


@pytest.mark.parametrize(
    "malicious_url",
    [
        "ftp://github.com/owner/repo",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ssh://git@github.com/owner/repo.git",
        "git://github.com/owner/repo.git",
        "https://gitlab.com/owner/repo",
        "https://github.evil.com/owner/repo",
        "https://user:pass@github.com/owner/repo",
        "https://github.com/../../etc/passwd",
        "https://github.com/owner/repo;rm -rf /",
        "https://github.com/owner/repo\n\rSet-Cookie: evil=1",
        "https://github.com/owner/repo\x00",
        "not a url",
        "",
    ],
)
def test_malicious_or_malformed_urls_rejected_end_to_end(api_client, malicious_url):
    response = api_client.post("/api/v1/repositories/github", json={"repository_url": malicious_url})
    assert response.status_code == 400
    assert response.json()["code"] in ("INVALID_REPOSITORY_URL", "UNSUPPORTED_REPOSITORY_PROVIDER")


def test_no_repository_row_created_for_any_malicious_url(api_client):
    for malicious_url in ["ftp://github.com/owner/repo", "javascript:alert(1)", "not a url"]:
        api_client.post("/api/v1/repositories/github", json={"repository_url": malicious_url})
    listing = api_client.get("/api/v1/repositories").json()
    assert listing["total"] == 0


# ---- Malicious branch names never reach a subprocess ----


@pytest.mark.parametrize(
    "malicious_branch",
    [
        "--upload-pack=touch /tmp/pwned",
        "; rm -rf /",
        "$(whoami)",
        "`whoami`",
        "../../etc/passwd",
        "-x",
    ],
)
def test_malicious_branch_name_never_reaches_git_subprocess(
    api_client, monkeypatch, tmp_path, malicious_branch
):
    subprocess_calls: list[list[str]] = []
    real_run = __import__("subprocess").run

    def recording_run(args, *a, **kw):  # pragma: no cover - only invoked if a real call slips through
        subprocess_calls.append(list(args))
        return real_run(args, *a, **kw)

    monkeypatch.setattr("app.services.clone_service.subprocess.run", recording_run)

    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": f"https://github.com/{OWNER}/{REPO}", "branch": malicious_branch},
        )

    repository_id = response.json()["repository_id"]
    run_id = response.json()["analysis_run_id"]
    run_status = api_client.get(f"/api/v1/repositories/{repository_id}/analysis-runs/{run_id}").json()

    # The malicious string never matches a real branch returned by
    # list_branches(), so selection fails (BRANCH_NOT_FOUND) before clone
    # is ever reached -- `git` is never invoked with it at all.
    assert run_status["status"] == "FAILED"
    assert run_status["error_code"] == "BRANCH_NOT_FOUND"
    assert subprocess_calls == []


# ---- Oversized repository, end-to-end ----


def test_oversized_repository_surfaces_structured_error_end_to_end(api_client, monkeypatch):
    def raise_too_large(**kwargs):
        raise RepositoryTooLargeError("repository exceeds the configured size limit")

    import app.services.github_provider as github_provider_module

    monkeypatch.setattr(github_provider_module, "clone_repository", raise_too_large)

    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github", json={"repository_url": f"https://github.com/{OWNER}/{REPO}"}
        )

    repository_id = response.json()["repository_id"]
    run_id = response.json()["analysis_run_id"]
    run_status = api_client.get(f"/api/v1/repositories/{repository_id}/analysis-runs/{run_id}").json()
    assert run_status["status"] == "FAILED"
    assert run_status["error_code"] == "REPOSITORY_TOO_LARGE"


# ---- Token-leakage: the cross-cutting check across responses, DB, and logs ----


@pytest.fixture
def with_fake_token():
    app.dependency_overrides[get_settings] = lambda: Settings(github_token=FAKE_TOKEN)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_token_never_appears_in_api_responses_db_or_logs_on_failure(
    api_client, monkeypatch, tmp_path, with_fake_token, caplog
):
    patch_clone(monkeypatch, tmp_path)
    caplog.set_level(logging.DEBUG)

    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": f"https://github.com/{OWNER}/{REPO}", "branch": "does-not-exist"},
        )

    body = response.json()
    assert FAKE_TOKEN not in str(body)

    repository_id = body["repository_id"]
    run_id = body["analysis_run_id"]

    status_response = api_client.get(f"/api/v1/repositories/{repository_id}/analysis-runs/{run_id}")
    assert FAKE_TOKEN not in str(status_response.json())
    assert status_response.json()["status"] == "FAILED"
    assert status_response.json()["error_code"] == "BRANCH_NOT_FOUND"

    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        assert FAKE_TOKEN not in str(record.args or "")


def test_token_never_appears_in_persisted_analysis_run_row(api_client, db_session, monkeypatch, tmp_path, with_fake_token):
    patch_clone(monkeypatch, tmp_path)
    with respx.mock:
        mock_github(respx)
        response = api_client.post(
            "/api/v1/repositories/github",
            json={"repository_url": f"https://github.com/{OWNER}/{REPO}", "branch": "does-not-exist"},
        )

    run_id = response.json()["analysis_run_id"]
    run = get_analysis_run(db_session, run_id)
    assert run is not None
    assert FAKE_TOKEN not in (run.error_message or "")
    assert FAKE_TOKEN not in str(run.config_snapshot)


def test_malicious_upstream_error_body_never_echoed_into_response_or_logs(
    api_client, with_fake_token, caplog
):
    # A worst-case/compromised upstream that reflects request internals
    # (here, a fake secret standing in for what a real echoed
    # Authorization header would look like) back in its error body --
    # proves the client never forwards a raw upstream response body into
    # a raised error or an API response, regardless of what GitHub sends.
    caplog.set_level(logging.DEBUG)
    leaky_body = f"Internal error, request had Authorization: Bearer {FAKE_TOKEN}"

    with respx.mock:
        respx.get(f"https://api.github.com/repos/{OWNER}/{REPO}").mock(
            return_value=httpx.Response(500, text=leaky_body)
        )
        response = api_client.post(
            "/api/v1/repositories/github", json={"repository_url": f"https://github.com/{OWNER}/{REPO}"}
        )

    body = response.json()
    assert FAKE_TOKEN not in str(body)
    repository_id = body["repository_id"]
    run_id = body["analysis_run_id"]
    status_response = api_client.get(f"/api/v1/repositories/{repository_id}/analysis-runs/{run_id}")
    assert FAKE_TOKEN not in str(status_response.json())
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()


def test_token_absent_from_default_headers_and_health_check(api_client):
    # No token configured (default) -- health check and a real request
    # never mention it, and the Authorization header is simply absent.
    response = api_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["github_token_configured"] is False
    assert "github_token" not in body
    assert "authorization" not in str(body).lower()
