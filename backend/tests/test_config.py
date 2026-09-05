from pathlib import Path

from app.core.config import Settings, get_settings


def test_has_github_token_false_when_none():
    settings = Settings(github_token=None)
    assert settings.has_github_token() is False


def test_has_github_token_false_when_empty_string():
    settings = Settings(github_token="")
    assert settings.has_github_token() is False


def test_has_github_token_true_when_whitespace_only():
    # Documented gap: a whitespace-only token is truthy and currently treated
    # as present, so a misconfigured env var would send "Bearer   " rather
    # than being caught here. Captured explicitly so a future tightening of
    # has_github_token() is a deliberate behavior change, not a surprise.
    settings = Settings(github_token="   ")
    assert settings.has_github_token() is True


def test_has_github_token_true_when_set():
    settings = Settings(github_token="ghp_abc123")
    assert settings.has_github_token() is True


def test_get_settings_returns_cached_singleton():
    first = get_settings()
    second = get_settings()
    assert first is second


def test_get_settings_cache_can_be_cleared_for_tests():
    get_settings.cache_clear()
    first = get_settings()
    get_settings.cache_clear()
    second = get_settings()
    assert first is not second


def test_workspace_root_defaults_under_backend_root():
    settings = Settings()
    assert settings.workspace_root == Path(settings.workspace_root)
    assert str(settings.workspace_root).endswith(str(Path(".workspace") / "repositories"))


def test_no_validation_currently_rejects_non_positive_retries():
    # Documented gap: github_max_retries has no lower-bound validation at the
    # Settings layer (GitHubApiClient floors it to 1 internally via max(...)).
    # This test captures today's permissive behavior so a future addition of
    # a ge=1 constraint is a deliberate, visible change.
    settings = Settings(github_max_retries=0)
    assert settings.github_max_retries == 0
    settings_negative = Settings(github_max_retries=-5)
    assert settings_negative.github_max_retries == -5


def test_no_validation_currently_rejects_negative_timeout():
    settings = Settings(github_request_timeout_seconds=-1.0)
    assert settings.github_request_timeout_seconds == -1.0
