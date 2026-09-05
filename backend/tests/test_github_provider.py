import httpx
import pytest
import respx

from app.core.config import Settings
from app.domain.repository_provider import get_provider_class_for_host
from app.services.github_client import GitHubApiClient
from app.services.github_provider import GitHubProvider

REPO_PAYLOAD = {
    "id": 123456,
    "name": "hello-world",
    "owner": {"login": "octocat"},
    "description": "My first repository",
    "default_branch": "main",
    "private": False,
    "language": "Python",
    "topics": ["demo", "example"],
    "license": {"name": "MIT License"},
    "stargazers_count": 42,
    "forks_count": 7,
    "open_issues_count": 3,
    "created_at": "2020-01-01T00:00:00Z",
    "updated_at": "2024-06-01T12:30:00Z",
}


@pytest.fixture
def settings():
    return Settings(github_max_retries=1, github_request_timeout_seconds=1.0)


def make_provider(settings: Settings) -> GitHubProvider:
    return GitHubProvider(settings=settings, client=GitHubApiClient(settings=settings))


def test_github_provider_registered_for_github_com():
    assert get_provider_class_for_host("github.com") is GitHubProvider
    assert get_provider_class_for_host("www.github.com") is GitHubProvider


@respx.mock
def test_fetch_metadata_maps_all_fields(settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    with make_provider(settings) as provider:
        metadata = provider.fetch_metadata("octocat", "hello-world")

    assert metadata.repository_id == "123456"
    assert metadata.owner == "octocat"
    assert metadata.name == "hello-world"
    assert metadata.default_branch == "main"
    assert metadata.visibility == "public"
    assert metadata.primary_language == "Python"
    assert metadata.topics == ["demo", "example"]
    assert metadata.license_name == "MIT License"
    assert metadata.stargazers_count == 42
    assert metadata.created_at is not None
    assert metadata.updated_at is not None


@respx.mock
def test_fetch_metadata_private_repository(settings):
    payload = dict(REPO_PAYLOAD, private=True)
    respx.get("https://api.github.com/repos/octocat/secret").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with make_provider(settings) as provider:
        metadata = provider.fetch_metadata("octocat", "secret")
    assert metadata.visibility == "private"


@respx.mock
def test_list_branches_marks_default_branch(settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"name": "main", "commit": {"sha": "abc123"}},
                {"name": "dev", "commit": {"sha": "def456"}},
            ],
        )
    )
    with make_provider(settings) as provider:
        branches = provider.list_branches("octocat", "hello-world")

    by_name = {b.name: b for b in branches}
    assert by_name["main"].is_default is True
    assert by_name["main"].head_commit_sha == "abc123"
    assert by_name["dev"].is_default is False


@respx.mock
def test_get_commit_history_maps_fields(settings):
    respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "sha": "abc123",
                    "parents": [{"sha": "parent1"}],
                    "commit": {
                        "message": "Fix bug",
                        "author": {
                            "name": "Ada Lovelace",
                            "email": "ada@example.com",
                            "date": "2024-01-15T09:00:00Z",
                        },
                    },
                }
            ],
        )
    )
    with make_provider(settings) as provider:
        commits = provider.get_commit_history("octocat", "hello-world", "main", limit=10)

    assert len(commits) == 1
    commit = commits[0]
    assert commit.sha == "abc123"
    assert commit.parents == ["parent1"]
    assert commit.author_name == "Ada Lovelace"
    assert commit.author_email == "ada@example.com"
    assert commit.message == "Fix bug"
    assert commit.committed_at is not None


@respx.mock
def test_get_commit_history_bounded_by_configured_max(settings):
    settings.max_commit_history = 2
    payloads = [
        {"sha": f"sha{i}", "parents": [], "commit": {"message": f"commit {i}", "author": {}}}
        for i in range(10)
    ]
    respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=httpx.Response(200, json=payloads)
    )
    with make_provider(settings) as provider:
        commits = provider.get_commit_history("octocat", "hello-world", "main", limit=10)

    assert len(commits) == 2


@respx.mock
def test_get_languages_returns_dict(settings):
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, json={"Python": 12345, "HTML": 678})
    )
    with make_provider(settings) as provider:
        languages = provider.get_languages("octocat", "hello-world")
    assert languages == {"Python": 12345, "HTML": 678}


def test_clone_builds_https_url_and_delegates_to_clone_service(settings, monkeypatch):
    # The actual git subprocess mechanics are tested against real local
    # repos in tests/test_clone_service.py. Here we only confirm
    # GitHubProvider.clone() constructs the right URL and hands off
    # correctly, without spawning a real subprocess.
    captured = {}

    def fake_run_git_clone(*, clone_url, branch, target_dir, settings):
        captured["clone_url"] = clone_url
        captured["branch"] = branch
        captured["target_dir"] = target_dir
        from datetime import datetime, timezone

        from app.domain.models import CloneResult

        return CloneResult(
            local_path=str(target_dir),
            commit_sha="deadbeef",
            branch=branch,
            cloned_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(
        "app.services.github_provider.clone_service.run_git_clone", fake_run_git_clone
    )

    provider = make_provider(settings)
    result = provider.clone("octocat", "hello-world", "main", "/tmp/somewhere")

    assert captured["clone_url"] == "https://github.com/octocat/hello-world.git"
    assert captured["branch"] == "main"
    assert captured["target_dir"].name == "somewhere"
    assert result.commit_sha == "deadbeef"
    provider.close()


@respx.mock
def test_list_branches_calls_fetch_metadata_internally(settings):
    # Documented inefficiency: list_branches() re-fetches repository metadata
    # (2 network calls total) purely to learn the default branch name. Not a
    # correctness bug, but flagged so a future optimization can verify it
    # actually reduces call count.
    metadata_route = respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=REPO_PAYLOAD)
    )
    respx.get("https://api.github.com/repos/octocat/hello-world/branches").mock(
        return_value=httpx.Response(200, json=[{"name": "main", "commit": {"sha": "abc"}}])
    )
    with make_provider(settings) as provider:
        provider.list_branches("octocat", "hello-world")
    assert metadata_route.call_count == 1


@respx.mock
def test_fetch_metadata_missing_owner_and_license_keys_entirely(settings):
    payload = dict(REPO_PAYLOAD)
    payload.pop("owner")
    payload.pop("license")
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with make_provider(settings) as provider:
        metadata = provider.fetch_metadata("octocat", "hello-world")
    assert metadata.owner == ""
    assert metadata.license_name is None


@respx.mock
def test_commit_with_no_parents(settings):
    respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "sha": "root",
                    "commit": {"message": "root commit", "author": {}},
                }
            ],
        )
    )
    with make_provider(settings) as provider:
        commits = provider.get_commit_history("octocat", "hello-world", "main", limit=10)
    assert commits[0].parents == []


@pytest.mark.parametrize(
    "body",
    [b"null", b"[]", b'"not-a-dict"', b"42"],
)
@respx.mock
def test_get_languages_non_dict_payload_returns_empty_dict(settings, body):
    respx.get("https://api.github.com/repos/octocat/hello-world/languages").mock(
        return_value=httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
    )
    with make_provider(settings) as provider:
        languages = provider.get_languages("octocat", "hello-world")
    assert languages == {}


def test_close_does_not_close_injected_client(settings):
    injected_client = GitHubApiClient(settings=settings)
    provider = GitHubProvider(settings=settings, client=injected_client)
    provider.close()
    # The injected client's underlying httpx.Client must still be usable
    # (not closed) because the provider does not own it.
    assert injected_client._client.is_closed is False
    injected_client.close()


def test_close_does_close_owned_client(settings):
    provider = GitHubProvider(settings=settings)
    owned_client = provider._client
    provider.close()
    assert owned_client._client.is_closed is True


def test_parse_github_datetime_malformed_returns_none():
    from app.services.github_provider import _parse_github_datetime

    assert _parse_github_datetime("not-a-date") is None
    assert _parse_github_datetime(None) is None
    assert _parse_github_datetime("") is None
