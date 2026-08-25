import httpx
import pytest
import respx

from app.core.config import Settings
from app.domain.errors import (
    MalformedUpstreamResponseError,
    RateLimitExceededError,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from app.services.github_client import GitHubApiClient


@pytest.fixture
def fast_settings():
    return Settings(github_max_retries=2, github_request_timeout_seconds=1.0)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr("app.services.github_client.time.sleep", lambda _seconds: None)


@respx.mock
def test_get_json_success(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "hello-world"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        payload = client.get_json("/repos/octocat/hello-world")
    assert payload == {"id": 1, "name": "hello-world"}


@respx.mock
def test_404_raises_not_found(fast_settings):
    respx.get("https://api.github.com/repos/octocat/missing").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RepositoryNotFoundError):
            client.get_json("/repos/octocat/missing")


@respx.mock
def test_401_raises_access_denied(fast_settings):
    respx.get("https://api.github.com/repos/octocat/private").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RepositoryAccessDeniedError):
            client.get_json("/repos/octocat/private")


@respx.mock
def test_403_without_rate_limit_headers_raises_access_denied(fast_settings):
    respx.get("https://api.github.com/repos/octocat/private").mock(
        return_value=httpx.Response(403, json={"message": "Forbidden"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RepositoryAccessDeniedError):
            client.get_json("/repos/octocat/private")


@respx.mock
def test_403_with_rate_limit_headers_raises_rate_limited(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
        )
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RateLimitExceededError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_429_with_retry_after_raises_rate_limited(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(429, json={"message": "You have exceeded a secondary rate limit"}, headers={"Retry-After": "30"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RateLimitExceededError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_429_without_retry_after_raises_rate_limited(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(429, json={"message": "You have exceeded a secondary rate limit"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(RateLimitExceededError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_timeout_raises_upstream_timeout(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(UpstreamTimeoutError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_persistent_500_raises_upstream_unavailable(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(UpstreamUnavailableError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_500_then_success_recovers_via_retry(fast_settings):
    route = respx.get("https://api.github.com/repos/octocat/hello-world")
    route.side_effect = [
        httpx.Response(500, json={"message": "Internal Server Error"}),
        httpx.Response(200, json={"id": 1}),
    ]
    with GitHubApiClient(settings=fast_settings) as client:
        payload = client.get_json("/repos/octocat/hello-world")
    assert payload == {"id": 1}


@respx.mock
def test_malformed_json_raises_malformed_response(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world").mock(
        return_value=httpx.Response(200, content=b"not json", headers={"Content-Type": "application/json"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(MalformedUpstreamResponseError):
            client.get_json("/repos/octocat/hello-world")


@respx.mock
def test_get_paginated_follows_link_header(fast_settings):
    base_url = "https://api.github.com/repos/octocat/hello-world/commits"
    page2_url = f"{base_url}?page=2"

    respx.get(base_url, params={"per_page": "10"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"sha": "a"}, {"sha": "b"}],
            headers={"Link": f'<{page2_url}>; rel="next"'},
        )
    )
    respx.get(base_url, params={"page": "2"}).mock(return_value=httpx.Response(200, json=[{"sha": "c"}]))

    with GitHubApiClient(settings=fast_settings) as client:
        results = client.get_paginated("/repos/octocat/hello-world/commits", limit=10)

    assert [r["sha"] for r in results] == ["a", "b", "c"]


@respx.mock
def test_get_paginated_stops_at_limit(fast_settings):
    base_url = "https://api.github.com/repos/octocat/hello-world/commits"
    page2_url = f"{base_url}?page=2"

    respx.get(base_url, params={"per_page": "3"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"sha": "a"}, {"sha": "b"}],
            headers={"Link": f'<{page2_url}>; rel="next"'},
        )
    )
    respx.get(base_url, params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[{"sha": "c"}, {"sha": "d"}])
    )

    with GitHubApiClient(settings=fast_settings) as client:
        results = client.get_paginated("/repos/octocat/hello-world/commits", limit=3)

    assert len(results) == 3


@respx.mock
def test_get_paginated_malformed_page_raises(fast_settings):
    respx.get("https://api.github.com/repos/octocat/hello-world/commits").mock(
        return_value=httpx.Response(200, json={"not": "a list"})
    )
    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(MalformedUpstreamResponseError):
            client.get_paginated("/repos/octocat/hello-world/commits", limit=10)


@respx.mock
def test_get_paginated_self_referencing_link_header_raises_instead_of_hanging(fast_settings):
    """Regression: a Link header whose "next" URL never actually advances
    (repeats the same URL, each page short of `per_page` items -- here,
    empty) used to make get_paginated() loop forever instead of ever
    reaching `limit` or running out of pages. A malformed/hostile upstream
    must fail fast with a structured error, not hang the ingestion job."""
    base_url = "https://api.github.com/repos/octocat/hello-world/commits"
    respx.get(base_url).mock(
        return_value=httpx.Response(200, json=[], headers={"Link": f'<{base_url}>; rel="next"'})
    )

    with GitHubApiClient(settings=fast_settings) as client:
        with pytest.raises(MalformedUpstreamResponseError):
            client.get_paginated("/repos/octocat/hello-world/commits", limit=10)


def test_token_never_appears_in_default_headers_when_unset():
    settings = Settings(github_token=None)
    with GitHubApiClient(settings=settings) as client:
        assert "Authorization" not in client._client.headers


def test_token_is_sent_as_bearer_header_when_configured():
    settings = Settings(github_token="super-secret-token")
    with GitHubApiClient(settings=settings) as client:
        assert client._client.headers["Authorization"] == "Bearer super-secret-token"
