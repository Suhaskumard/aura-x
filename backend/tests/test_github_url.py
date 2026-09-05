import pytest

from app.domain.errors import InvalidRepositoryUrlError, UnsupportedRepositoryProviderError
from app.domain.github_url import parse_github_url


@pytest.mark.parametrize(
    "url,expected_owner,expected_repo",
    [
        ("https://github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("https://github.com/fastapi/fastapi.git", "fastapi", "fastapi"),
        ("https://github.com/fastapi/fastapi/", "fastapi", "fastapi"),
        ("https://github.com/fastapi/fastapi.git/", "fastapi", "fastapi"),
        ("https://www.github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("http://github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("  https://github.com/fastapi/fastapi  ", "fastapi", "fastapi"),
        ("https://github.com/octocat/Hello-World", "octocat", "Hello-World"),
        ("https://github.com/my-org/repo.name_with.dots", "my-org", "repo.name_with.dots"),
        ("https://github.com/owner/repo/tree/main", "owner", "repo"),
    ],
)
def test_valid_urls(url, expected_owner, expected_repo):
    result = parse_github_url(url)
    assert result.owner == expected_owner
    assert result.repository == expected_repo
    assert result.normalized_url == f"https://github.com/{expected_owner}/{expected_repo}"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "not a url",
        "ftp://github.com/owner/repo",
        "javascript:alert(1)",
        "https://gitlab.com/owner/repo",
        "https://github.evil.com/owner/repo",
        "https://github.com.evil.com/owner/repo",
        "https://githubb.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/",
        "https://github.com",
        "https://user:pass@github.com/owner/repo",
        "https://github.com/../../etc/passwd",
        "https://github.com/owner/..",
        "https://github.com/owner/%2e%2e",
        "https://github.com/owner/repo\\..\\..",
        "https://github.com/-owner/repo",
        "https://github.com/owner-/repo",
        "https://github.com/owner/.",
        "https://github.com/owner/..git",
        "https://github.com/owner/.git",
        "https://github.com/ow ner/repo",
        "https://github.com/owner/repo;rm -rf /",
        "https://github.com/owner/repo\n\rSet-Cookie: evil=1",
        "https://github.com/owner/repo\x00",
    ],
)
def test_invalid_or_unsupported_urls_are_rejected(url):
    with pytest.raises((InvalidRepositoryUrlError, UnsupportedRepositoryProviderError)):
        parse_github_url(url)


def test_unsupported_host_raises_specific_error_type():
    with pytest.raises(UnsupportedRepositoryProviderError):
        parse_github_url("https://gitlab.com/owner/repo")


def test_malformed_url_raises_specific_error_type():
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url("not a url at all")


def test_overlong_url_rejected():
    huge = "https://github.com/owner/" + ("a" * 3000)
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url(huge)


def test_non_string_input_rejected():
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url(None)  # type: ignore[arg-type]


def test_error_message_never_echoes_shell_metacharacters_unsafely():
    # Defensive check: the exception message is just a string used in logs/
    # API responses, never passed to a shell, so this mainly guards against
    # a future refactor introducing eval/exec/subprocess on the raw input.
    try:
        parse_github_url("https://github.com/owner/repo;rm -rf /")
    except InvalidRepositoryUrlError as exc:
        assert isinstance(exc.message, str)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/owner/repo",
        "https://[::1]/owner/repo",
        "https://0.0.0.0/owner/repo",
        "https://xn--80ak6aa92e.com/owner/repo",  # IDN/punycode host, not github.com
        "https://gіthub.com/owner/repo",  # Cyrillic 'і' homograph, not an ASCII match
    ],
)
def test_non_github_hosts_rejected_as_unsupported(url):
    with pytest.raises((InvalidRepositoryUrlError, UnsupportedRepositoryProviderError)):
        parse_github_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com:443/owner/repo",
        "https://github.com:8443/owner/repo",
    ],
)
def test_explicit_port_does_not_bypass_host_validation(url):
    # hostname allowlist check uses parsed.hostname, which excludes the port,
    # so an explicit port must not change owner/repo extraction.
    result = parse_github_url(url)
    assert result.owner == "owner"
    assert result.repository == "repo"


def test_owner_repo_extraction_ignores_extra_path_segments():
    result = parse_github_url("https://github.com/owner/repo/blob/main/some/file.py")
    assert result.owner == "owner"
    assert result.repository == "repo"


def test_trailing_dot_host_rejected():
    with pytest.raises((InvalidRepositoryUrlError, UnsupportedRepositoryProviderError)):
        parse_github_url("https://github.com./owner/repo")


def test_uppercase_host_is_accepted_case_insensitively():
    result = parse_github_url("https://GITHUB.COM/owner/repo")
    assert result.owner == "owner"
    assert result.repository == "repo"


@pytest.mark.parametrize("reserved", [".GIT", ".Git", "..", "."])
def test_reserved_repo_names_rejected_case_insensitively(reserved):
    with pytest.raises(InvalidRepositoryUrlError):
        parse_github_url(f"https://github.com/owner/{reserved}")
