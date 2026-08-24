from app.domain.models import BranchInfo, CloneResult, CommitInfo, RepositoryMetadata
from app.domain.repository_provider import (
    RepositoryProvider,
    get_provider_class_for_host,
    register_provider,
    registered_hosts,
)


class FakeProvider(RepositoryProvider):
    """Minimal concrete implementation used only to prove the abstraction
    is usable and the registry works, without any network access."""

    name = "fake"

    def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        return RepositoryMetadata(
            repository_id=f"{owner}/{repo}",
            name=repo,
            owner=owner,
            description=None,
            default_branch="main",
            visibility="public",
            primary_language="Python",
        )

    def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
        return [BranchInfo(name="main", head_commit_sha="deadbeef", is_default=True)]

    def get_commit_history(self, owner: str, repo: str, branch: str, limit: int) -> list[CommitInfo]:
        return []

    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        return {"Python": 100}

    def clone(self, owner: str, repo: str, branch: str, target_dir: str) -> CloneResult:
        from datetime import datetime, timezone

        return CloneResult(
            local_path=target_dir,
            commit_sha="deadbeef",
            branch=branch,
            cloned_at=datetime.now(timezone.utc),
        )


def test_repository_provider_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        RepositoryProvider()  # cannot instantiate the ABC directly


def test_fake_provider_implements_full_interface():
    provider = FakeProvider()
    metadata = provider.fetch_metadata("octocat", "hello-world")
    assert metadata.owner == "octocat"
    branches = provider.list_branches("octocat", "hello-world")
    assert branches[0].is_default is True


def test_provider_registry_round_trip():
    register_provider("example.test", FakeProvider)
    assert get_provider_class_for_host("EXAMPLE.TEST") is FakeProvider  # case-insensitive
    assert "example.test" in registered_hosts()


def test_unregistered_host_returns_none():
    assert get_provider_class_for_host("not-a-registered-host.invalid") is None
