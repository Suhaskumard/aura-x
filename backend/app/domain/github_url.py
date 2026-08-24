"""
GitHub repository URL parsing and validation.

Turns arbitrary user input into a validated (owner, repository) pair
before any network or filesystem action occurs. See docs/GITHUB_INTEGRATION.md
"Error handling" for the structured error codes raised here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from app.domain.errors import InvalidRepositoryUrlError, UnsupportedRepositoryProviderError

SUPPORTED_HOSTS = frozenset({"github.com", "www.github.com"})

# GitHub owner/repo naming rules (documented by GitHub):
# - owner: alphanumeric or single hyphens, cannot start/end with a hyphen, max 39 chars
# - repo: alphanumeric, hyphen, underscore, dot; cannot be "." or ".."; max 100 chars
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_RESERVED_REPO_NAMES = frozenset({".", "..", ".git"})


@dataclass(frozen=True, slots=True)
class ParsedGitHubUrl:
    owner: str
    repository: str
    normalized_url: str


def validate_owner_repo(owner: str, repo: str) -> None:
    """Validate an (owner, repo) pair against GitHub's naming rules.

    Shared by parse_github_url() and app/services/clone_service.py, which
    must re-validate defensively since it can be called with a raw
    (owner, repo, branch) tuple that never passed through URL parsing.
    """
    if not _OWNER_RE.match(owner):
        raise InvalidRepositoryUrlError(f"Invalid repository owner: {owner!r}")
    if repo.lower() in _RESERVED_REPO_NAMES or not _REPO_RE.match(repo):
        raise InvalidRepositoryUrlError(f"Invalid repository name: {repo!r}")


def parse_github_url(raw_url: str) -> ParsedGitHubUrl:
    """Validate and normalize a GitHub repository URL.

    Accepts:
      https://github.com/owner/repository
      https://github.com/owner/repository.git
      https://github.com/owner/repository/

    Raises InvalidRepositoryUrlError for malformed/malicious input and
    UnsupportedRepositoryProviderError for a well-formed URL pointing at a
    host other than github.com.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise InvalidRepositoryUrlError("Repository URL must be a non-empty string")

    candidate = raw_url.strip()
    if not candidate:
        raise InvalidRepositoryUrlError("Repository URL must be a non-empty string")

    if len(candidate) > 2048:
        raise InvalidRepositoryUrlError("Repository URL is too long")

    # Reject control characters, including embedded newlines/nulls used for
    # header/log injection or to smuggle a second URL.
    if any(unicodedata.category(ch) == "Cc" for ch in candidate):
        raise InvalidRepositoryUrlError("Repository URL contains control characters")

    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise InvalidRepositoryUrlError(f"Repository URL could not be parsed: {exc}") from None

    if parsed.scheme not in ("https", "http"):
        raise InvalidRepositoryUrlError(
            f"Unsupported URL scheme '{parsed.scheme or ''}': only http(s) is allowed"
        )

    if not parsed.hostname:
        raise InvalidRepositoryUrlError("Repository URL is missing a hostname")

    if parsed.username or parsed.password:
        raise InvalidRepositoryUrlError("Repository URL must not contain embedded credentials")

    hostname = parsed.hostname.lower()
    if hostname not in SUPPORTED_HOSTS:
        raise UnsupportedRepositoryProviderError(
            f"Unsupported repository provider host: {hostname}"
        )

    path = parsed.path or ""
    # Reject encoded/relative traversal attempts outright.
    if ".." in path or "%2e%2e" in path.lower() or "\\" in path:
        raise InvalidRepositoryUrlError("Repository URL path is not permitted")

    segments = [seg for seg in path.split("/") if seg]
    if len(segments) < 2:
        raise InvalidRepositoryUrlError(
            "Repository URL must include both an owner and a repository name"
        )

    owner, repo = segments[0], segments[1]

    if repo.endswith(".git"):
        repo = repo[: -len(".git")]

    validate_owner_repo(owner, repo)

    normalized_url = f"https://github.com/{owner}/{repo}"
    return ParsedGitHubUrl(owner=owner, repository=repo, normalized_url=normalized_url)
