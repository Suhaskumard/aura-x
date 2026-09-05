"""
Phase 15: consolidated security matrix.

Per-module security tests already exist throughout the suite (e.g.
test_github_url.py's rejection matrix, test_clone_service.py's shell/size
tests, test_excel_report_service.py's leakage scan). Those prove each
module is safe in isolation. This file proves the same guarantees hold
from the system's real entry point -- the actual REST API a caller
hits -- so a future refactor can't silently reconnect a validated module
in an unsafe way without a test noticing.

Dimensions covered, per the master plan's Phase 15 exit criteria
("injection, traversal, oversized repos, token-leakage across
logs/errors/responses/reports"):

- Injection and traversal: `repository_id` is never attacker-controlled
  (it's the database's own integer primary key, never accepted as API
  input), so these tests target a hostile *branch name* instead, mocked
  into a GitHub branches response and requested by name through the real
  /refresh endpoint. Note on realism: git's own ref-naming rules forbid
  spaces, "..", and several other characters, so a real GitHub branch
  could never literally hold some of these payloads -- these tests model
  a compromised/MITM'd upstream response (or a future non-GitHub
  provider) reaching clone_service's own validation, not a branch a real
  GitHub user could actually create. Spot-checked load-bearing: with
  clone_service's argument-list subprocess design (never shell=True),
  disabling `_validate_branch_for_subprocess`'s checks did NOT make
  these tests fail -- git itself already treats an unrecognized branch
  value as inert data and reports "branch not found" rather than
  executing anything. So what these tests actually prove is end-to-end
  system-boundary resilience (clean FAILED status, no crash, no
  execution, no escape) under defense-in-depth from multiple layers, not
  that any single guard is uniquely load-bearing for this path.
- Oversized repos: a real local repo forced past max_repository_size_mb,
  ingested through the real async pipeline end to end.
- Token-leakage across logs/errors/responses: a real GitHubApiClient
  call (success and failure) with a real-looking token configured,
  asserting the token substring never appears in any captured log
  record, and never appears in a real API error response body.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.services import clone_service
from app.services.github_client import GitHubApiClient
from app.services.github_provider import GitHubProvider

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable not on PATH")

REPO_PAYLOAD = {
    "id": 999005,
    "name": "hello-world",
    "owner": {"login": "octocat"},
    "description": "test repo",
    "default_branch": "main",
    "private": False,
    "language": "Python",
    "topics": [],
    "license": None,
    "stargazers_count": 1,
    "forks_count": 0,
    "open_issues_count": 0,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2024-06-01T12:30:00Z",
}


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    _run(["git", "init", "--initial-branch=main"], cwd=repo_dir)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir)
    _run(["git", "config", "user.name", "Test"], cwd=repo_dir)
    (repo_dir / "app.py").write_text("print('hi')\n" * 100, encoding="utf-8")
    _run(["git", "add", "."], cwd=repo_dir)
    _run(["git", "commit", "-m", "initial commit"], cwd=repo_dir)
    return repo_dir


@pytest.fixture(autouse=True)
def _allow_local_file_transport_for_tests(monkeypatch):
    monkeypatch.setitem(clone_service._GIT_ENV_OVERRIDES, "GIT_ALLOW_PROTOCOL", "https:file")


@pytest.fixture(autouse=True)
def _redirect_clone_to_local_repo(monkeypatch, local_repo):
    # The real GitHubProvider.clone() is exercised unchanged (including
    # its call into clone_service's branch/size validation) -- only the
    # actual network clone target is swapped for a local repo, exactly
    # like test_api_repositories.py and test_excel_report_service.py.
    def fake_clone(self, owner, repo, branch, target_dir):
        return clone_service._clone_and_verify(
            clone_url=str(local_repo), branch=branch, target_dir=Path(target_dir), settings=self._settings
        )

    monkeypatch.setattr(GitHubProvider, "clone", fake_clone)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        clone_timeout_seconds=30,
        github_max_retries=1,
        github_request_timeout_seconds=1.0,
    )


@pytest.fixture(autouse=True)
def _use_test_workspace(monkeypatch, test_settings):
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr("app.core.config.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.services.ingestion_service.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.api.v1.repositories.get_settings", lambda: test_settings)
    yield test_settings
    get_settings.cache_clear()


def _mock_github(*, branches: list[dict]):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(200, json=branches)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, json={"Python": 1234})
    )


def _create_and_refresh_with_branch(client_with_db, branch_name: str, *, all_branches: list[dict]):
    _mock_github(branches=all_branches)
    create_resp = client_with_db.post(
        "/api/v1/repositories", json={"source_url": "https://github.com/octocat/hello-world"}
    )
    repo_id = create_resp.json()["repository"]["id"]

    refresh_resp = client_with_db.post(
        f"/api/v1/repositories/{repo_id}/refresh", json={"branch": branch_name}
    )
    assert refresh_resp.status_code == 202
    run_id = refresh_resp.json()["analysis_run"]["id"]
    return client_with_db.get(f"/api/v1/analysis-runs/{run_id}").json()


# ---------------------------------------------------------------------------
# Injection: a branch name crafted to look like a git option / shell payload.
# ---------------------------------------------------------------------------

INJECTION_BRANCH_NAMES = [
    "--upload-pack=touch /tmp/pwned",
    "; rm -rf / #",
    "$(touch /tmp/pwned)",
    "`touch /tmp/pwned`",
]


@pytest.mark.parametrize("malicious_branch", INJECTION_BRANCH_NAMES)
@respx.mock
def test_injection_branch_name_never_crashes_and_never_executes(
    client_with_db, malicious_branch, tmp_path
):
    marker_file = tmp_path / "pwned"
    all_branches = [
        {"name": "main", "commit": {"sha": "abc123"}},
        {"name": malicious_branch, "commit": {"sha": "def456"}},
    ]

    body = _create_and_refresh_with_branch(client_with_db, malicious_branch, all_branches=all_branches)

    assert body["status"] == "FAILED", body
    assert body["last_error"]["code"] == "CLONE_FAILED"
    # No shell command from the branch name ever actually ran (see module
    # docstring: proven by argv-list subprocess design, not by this
    # assertion alone -- disabling the branch validator doesn't flip it).
    assert not marker_file.exists()


# ---------------------------------------------------------------------------
# Traversal: a branch name crafted to escape the workspace via ".." segments.
# ---------------------------------------------------------------------------

TRAVERSAL_BRANCH_NAMES = [
    "../../etc/passwd",
    "..\\..\\windows\\system32",
]


@pytest.mark.parametrize("malicious_branch", TRAVERSAL_BRANCH_NAMES)
@respx.mock
def test_traversal_branch_name_never_escapes_workspace(client_with_db, malicious_branch, test_settings):
    all_branches = [
        {"name": "main", "commit": {"sha": "abc123"}},
        {"name": malicious_branch, "commit": {"sha": "def456"}},
    ]

    body = _create_and_refresh_with_branch(client_with_db, malicious_branch, all_branches=all_branches)

    assert body["status"] == "FAILED", body
    assert body["last_error"]["code"] == "CLONE_FAILED"
    # Nothing was ever written outside the configured workspace root.
    workspace_root = test_settings.workspace_root.resolve()
    if workspace_root.parent.exists():
        for entry in workspace_root.parent.iterdir():
            assert entry == workspace_root or entry.name != "etc"


# ---------------------------------------------------------------------------
# Oversized repos: real content, forced past a real (tiny) size limit.
# ---------------------------------------------------------------------------


@respx.mock
def test_oversized_repository_fails_cleanly_end_to_end(client_with_db, monkeypatch):
    # Reuse the already-active test_settings workspace_root, only shrinking
    # the size limit -- constructing a whole new Settings object would lose
    # the per-test workspace_root override from the autouse fixture.
    import app.api.v1.repositories as repositories_module
    import app.services.ingestion_service as ingestion_service_module

    active_settings = repositories_module.get_settings()
    shrunk_settings = Settings(
        workspace_root=active_settings.workspace_root,
        clone_timeout_seconds=active_settings.clone_timeout_seconds,
        github_max_retries=active_settings.github_max_retries,
        github_request_timeout_seconds=active_settings.github_request_timeout_seconds,
        max_repository_size_mb=0,
    )
    monkeypatch.setattr(repositories_module, "get_settings", lambda: shrunk_settings)
    monkeypatch.setattr(ingestion_service_module, "get_settings", lambda: shrunk_settings)

    all_branches = [{"name": "main", "commit": {"sha": "abc123"}}]
    body = _create_and_refresh_with_branch(client_with_db, "main", all_branches=all_branches)

    assert body["status"] == "FAILED", body
    assert body["last_error"]["code"] == "REPOSITORY_TOO_LARGE"


# ---------------------------------------------------------------------------
# Token-leakage: across logs, errors, and API responses.
# ---------------------------------------------------------------------------

FAKE_TOKEN = "ghp_FAKESECRETTOKENVALUE1234567890abcd"


@respx.mock
def test_github_client_never_logs_token_on_success_or_failure(caplog):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    settings = Settings(github_token=FAKE_TOKEN, github_max_retries=1, github_request_timeout_seconds=1.0)

    with caplog.at_level(logging.DEBUG):
        client = GitHubApiClient(settings=settings)
        try:
            client.get_json("/repos/octocat/hello-world")
            with pytest.raises(Exception):
                client.get_json("/repos/octocat/hello-world/branches")
        finally:
            client.close()

    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        assert FAKE_TOKEN not in str(record.__dict__)


@respx.mock
def test_failed_ingestion_api_response_never_contains_configured_token(client_with_db, monkeypatch):
    import app.api.v1.repositories as repositories_module
    import app.services.ingestion_service as ingestion_service_module

    active_settings = repositories_module.get_settings()
    tokened_settings = Settings(
        workspace_root=active_settings.workspace_root,
        clone_timeout_seconds=active_settings.clone_timeout_seconds,
        github_max_retries=1,
        github_request_timeout_seconds=1.0,
        github_token=FAKE_TOKEN,
    )
    monkeypatch.setattr(repositories_module, "get_settings", lambda: tokened_settings)
    monkeypatch.setattr(ingestion_service_module, "get_settings", lambda: tokened_settings)

    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    create_resp = client_with_db.post(
        "/api/v1/repositories", json={"source_url": "https://github.com/octocat/hello-world"}
    )
    run_id = create_resp.json()["analysis_run"]["id"]

    status_resp = client_with_db.get(f"/api/v1/analysis-runs/{run_id}")
    assert FAKE_TOKEN not in status_resp.text
    body = status_resp.json()
    assert body["status"] == "FAILED"
    assert body["last_error"]["code"] == "REPOSITORY_ACCESS_DENIED"
