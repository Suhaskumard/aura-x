"""
Low-level GitHub REST API HTTP client.

This is the ONLY module in the codebase allowed to make an HTTP request to
api.github.com. Everything else goes through GitHubProvider
(app/services/github_provider.py), which wraps this client and returns
provider-agnostic domain types (app/domain/models.py).

Never logs the Authorization header or a token value. Every httpx/GitHub
failure mode is translated into an app.domain.errors type before it
leaves this module -- callers never see a raw httpx exception or a raw
GitHub error payload.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.domain.errors import (
    MalformedUpstreamResponseError,
    RateLimitExceededError,
    RepositoryAccessDeniedError,
    RepositoryNotFoundError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})


def _backoff_seconds(attempt: int) -> float:
    return min(2**attempt * 0.1, 2.0)


def _is_rate_limited(response: httpx.Response) -> bool:
    return response.headers.get("X-RateLimit-Remaining") == "0"


def _rate_limit_reset_at(response: httpx.Response) -> str:
    reset_header = response.headers.get("X-RateLimit-Reset")
    if not reset_header:
        return "unknown"
    try:
        return datetime.fromtimestamp(int(reset_header), tz=timezone.utc).isoformat()
    except (ValueError, OSError):
        return "unknown"


def _next_link(response: httpx.Response) -> str | None:
    """Extract the rel="next" URL from a GitHub Link header, if present."""
    link_header = response.headers.get("Link")
    if not link_header:
        return None
    for part in link_header.split(","):
        segment = part.strip()
        if 'rel="next"' not in segment:
            continue
        start = segment.find("<")
        end = segment.find(">")
        if start != -1 and end != -1 and end > start:
            return segment[start + 1 : end]
    return None


class GitHubApiClient:
    """Thin, structured wrapper around the GitHub REST API."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._settings = settings or get_settings()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._settings.has_github_token():
            headers["Authorization"] = f"Bearer {self._settings.github_token.get_secret_value()}"
        self._client = httpx.Client(
            base_url=self._settings.github_api_base_url,
            headers=headers,
            timeout=self._settings.github_request_timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubApiClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, url: str, *, params: dict | None = None) -> httpx.Response:
        last_exc: Exception | None = None
        max_attempts = max(self._settings.github_max_retries, 1)

        for attempt in range(1, max_attempts + 1):
            try:
                response = self._client.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise UpstreamTimeoutError(f"GitHub API request timed out: {method} {url}") from None
                time.sleep(_backoff_seconds(attempt))
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt >= max_attempts:
                    raise UpstreamUnavailableError(f"GitHub API request failed: {method} {url}") from None
                time.sleep(_backoff_seconds(attempt))
                continue

            if response.status_code == 404:
                raise RepositoryNotFoundError(f"GitHub resource not found: {url}")
            if response.status_code == 401:
                raise RepositoryAccessDeniedError(
                    "GitHub authentication failed (missing or invalid token)"
                )
            if response.status_code == 403:
                if _is_rate_limited(response):
                    raise RateLimitExceededError(
                        f"GitHub API rate limit exceeded, resets at {_rate_limit_reset_at(response)}"
                    )
                raise RepositoryAccessDeniedError(
                    "GitHub access denied (private repository or insufficient token scope)"
                )
            if response.status_code == 429:
                # GitHub's secondary rate limit (abuse detection) responds
                # with 429, not 403, and does not always send the
                # X-RateLimit-* headers used by _is_rate_limited().
                raise RateLimitExceededError(
                    f"GitHub API secondary rate limit exceeded, resets at {_rate_limit_reset_at(response)}"
                )
            if response.status_code in _RETRYABLE_STATUS_CODES:
                last_exc = None
                if attempt >= max_attempts:
                    raise UpstreamUnavailableError(
                        f"GitHub API returned {response.status_code} for {method} {url}"
                    )
                time.sleep(_backoff_seconds(attempt))
                continue
            if response.status_code >= 400:
                raise UpstreamUnavailableError(
                    f"GitHub API returned unexpected status {response.status_code} for {method} {url}"
                )
            return response

        raise UpstreamUnavailableError(
            f"GitHub API request failed after {max_attempts} attempt(s): {method} {url}"
        ) from last_exc

    def get_json(self, path: str, *, params: dict | None = None) -> Any:
        response = self._request("GET", path, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise MalformedUpstreamResponseError(
                f"GitHub API returned malformed JSON for {path}"
            ) from exc

    def get_paginated(self, path: str, *, limit: int, params: dict | None = None) -> list[Any]:
        """Follow GitHub's Link-header pagination, collecting up to `limit` items."""
        results: list[Any] = []
        next_url: str | None = path
        next_params: dict | None = dict(params or {})
        next_params.setdefault("per_page", min(100, max(limit, 1)))

        while next_url and len(results) < limit:
            response = self._request("GET", next_url, params=next_params)
            try:
                page = response.json()
            except ValueError as exc:
                raise MalformedUpstreamResponseError(
                    f"GitHub API returned malformed JSON for {next_url}"
                ) from exc
            if not isinstance(page, list):
                raise MalformedUpstreamResponseError(f"Expected a JSON array from {next_url}")
            results.extend(page)
            next_url = _next_link(response)
            next_params = None  # the Link header URL already carries its own query params

        return results[:limit]
