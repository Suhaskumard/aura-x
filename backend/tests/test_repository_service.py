import pytest

from app.domain.errors import BranchNotFoundError
from app.domain.models import BranchInfo, CloneResult, CommitInfo, RepositoryMetadata
from app.domain.repository_provider import RepositoryProvider
from app.services.repository_service import resolve_branch


class StubProvider(RepositoryProvider):
    name = "stub"

    def __init__(self, branches: list[BranchInfo]):
        self._branches = branches

    def fetch_metadata(self, owner: str, repo: str) -> RepositoryMetadata:
        raise NotImplementedError

    def list_branches(self, owner: str, repo: str) -> list[BranchInfo]:
        return self._branches

    def get_commit_history(self, owner, repo, branch, limit) -> list[CommitInfo]:
        raise NotImplementedError

    def get_languages(self, owner: str, repo: str) -> dict[str, int]:
        raise NotImplementedError

    def clone(self, owner, repo, branch, target_dir) -> CloneResult:
        raise NotImplementedError


def make_provider() -> StubProvider:
    return StubProvider(
        [
            BranchInfo(name="main", head_commit_sha="main-sha", is_default=True),
            BranchInfo(name="develop", head_commit_sha="dev-sha", is_default=False),
        ]
    )


def test_resolve_branch_uses_default_when_none_requested():
    provider = make_provider()
    branch = resolve_branch(provider, "octocat", "hello-world", None)
    assert branch.name == "main"
    assert branch.head_commit_sha == "main-sha"


def test_resolve_branch_selects_requested_existing_branch():
    provider = make_provider()
    branch = resolve_branch(provider, "octocat", "hello-world", "develop")
    assert branch.name == "develop"
    assert branch.head_commit_sha == "dev-sha"


def test_resolve_branch_raises_for_unknown_branch():
    provider = make_provider()
    with pytest.raises(BranchNotFoundError):
        resolve_branch(provider, "octocat", "hello-world", "does-not-exist")


def test_resolve_branch_raises_when_no_default_branch_marked():
    provider = StubProvider(
        [BranchInfo(name="main", head_commit_sha="main-sha", is_default=False)]
    )
    with pytest.raises(BranchNotFoundError):
        resolve_branch(provider, "octocat", "hello-world", None)


def test_resolve_branch_case_sensitive_branch_name():
    provider = make_provider()
    with pytest.raises(BranchNotFoundError):
        resolve_branch(provider, "octocat", "hello-world", "Main")
