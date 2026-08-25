"""
Phase 9: Repository (data-access) layer round-trip tests -- write then
read back through app.db.repository_dao, no ad hoc queries.
"""

from datetime import datetime, timezone

from app.db.repository_dao import (
    complete_analysis_run,
    create_analysis_run,
    get_analysis_run,
    get_repository_by_id,
    get_repository_by_identity,
    list_analysis_runs_for_repository,
    transition_analysis_run,
    upsert_branches,
    upsert_commits,
    upsert_repository,
)
from app.domain.models import BranchInfo, CommitInfo, FileChange, RepositoryMetadata
from app.domain.repository_context import IngestionStatus


def make_metadata(**overrides) -> RepositoryMetadata:
    defaults = dict(
        repository_id="123456",
        name="hello-world",
        owner="octocat",
        description="My first repository",
        default_branch="main",
        visibility="public",
        primary_language="Python",
        topics=["demo"],
        license_name="MIT License",
        stargazers_count=42,
        forks_count=7,
        open_issues_count=3,
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return RepositoryMetadata(**defaults)


def test_upsert_repository_creates_row(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
        metadata=make_metadata(),
    )
    db_session.commit()

    fetched = get_repository_by_id(db_session, repository.id)
    assert fetched is not None
    assert fetched.owner == "octocat"
    assert fetched.name == "hello-world"
    assert fetched.provider_repository_id == "123456"
    assert fetched.stargazers_count == 42
    assert fetched.topics == ["demo"]


def test_upsert_repository_is_idempotent_by_identity(db_session):
    first = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
        metadata=make_metadata(stargazers_count=1),
    )
    db_session.commit()

    second = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
        metadata=make_metadata(stargazers_count=999),
    )
    db_session.commit()

    assert first.id == second.id
    assert get_repository_by_identity(db_session, provider="github", owner="octocat", name="hello-world").id == first.id
    assert second.stargazers_count == 999  # updated in place, not duplicated


def test_upsert_branches_round_trip_and_dedup(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
    )
    branches = upsert_branches(
        db_session,
        repository,
        [
            BranchInfo(name="main", head_commit_sha="sha1", is_default=True),
            BranchInfo(name="dev", head_commit_sha="sha2", is_default=False),
        ],
    )
    db_session.commit()

    assert {b.name for b in branches} == {"main", "dev"}
    reloaded = get_repository_by_id(db_session, repository.id)
    assert len(reloaded.branches) == 2

    # Re-ingesting with a moved head and a dropped branch updates in place
    # and removes the stale one, rather than accumulating duplicates.
    upsert_branches(
        db_session, repository, [BranchInfo(name="main", head_commit_sha="sha3", is_default=True)]
    )
    db_session.commit()

    reloaded = get_repository_by_id(db_session, repository.id)
    assert len(reloaded.branches) == 1
    assert reloaded.branches[0].head_commit_sha == "sha3"


def test_upsert_commits_round_trip_with_changed_files(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
    )
    commits = [
        CommitInfo(
            sha="abc123",
            parents=["parent1"],
            author_name="Ada Lovelace",
            author_email="ada@example.com",
            committed_at=datetime(2024, 1, 15, tzinfo=timezone.utc),
            message="Fix bug",
            additions=5,
            deletions=2,
            changed_files=[FileChange(path="app/main.py", additions=5, deletions=2, status="modified")],
        )
    ]
    upsert_commits(db_session, repository, commits)
    db_session.commit()

    reloaded = get_repository_by_id(db_session, repository.id)
    assert len(reloaded.commits) == 1
    commit = reloaded.commits[0]
    assert commit.sha == "abc123"
    assert commit.parents == ["parent1"]
    assert commit.changed_files == [
        {"path": "app/main.py", "additions": 5, "deletions": 2, "status": "modified"}
    ]


def test_upsert_commits_never_deletes_prior_history(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
    )
    upsert_commits(db_session, repository, [CommitInfo(sha="a", parents=[], author_name=None, author_email=None, committed_at=None, message="first")])
    db_session.commit()

    upsert_commits(db_session, repository, [CommitInfo(sha="b", parents=[], author_name=None, author_email=None, committed_at=None, message="second")])
    db_session.commit()

    reloaded = get_repository_by_id(db_session, repository.id)
    assert {c.sha for c in reloaded.commits} == {"a", "b"}


def test_full_lineage_round_trip_repository_branch_commit_analysis_run(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
        metadata=make_metadata(),
    )
    upsert_branches(db_session, repository, [BranchInfo(name="main", head_commit_sha="sha1", is_default=True)])
    upsert_commits(
        db_session,
        repository,
        [CommitInfo(sha="sha1", parents=[], author_name="Ada", author_email="ada@example.com", committed_at=None, message="init")],
    )
    run = create_analysis_run(
        db_session,
        repository,
        branch_name="main",
        commit_sha="sha1",
        config_snapshot={"max_commit_history": 200},
    )
    for status in [
        IngestionStatus.VALIDATING,
        IngestionStatus.FETCHING_METADATA,
        IngestionStatus.FETCHING_BRANCHES,
        IngestionStatus.CLONING,
        IngestionStatus.SCANNING,
    ]:
        transition_analysis_run(db_session, run, status)
    complete_analysis_run(db_session, run, result_profile={"languages": {"Python": 500}})
    db_session.commit()
    run_id, repository_id = run.id, repository.id

    # Fresh reads (simulating a new request) walk the full chain.
    reloaded_repo = get_repository_by_id(db_session, repository_id)
    reloaded_run = get_analysis_run(db_session, run_id)
    runs_for_repo = list_analysis_runs_for_repository(db_session, repository_id)

    assert reloaded_repo.owner == "octocat"
    assert reloaded_repo.branches[0].name == "main"
    assert reloaded_repo.commits[0].sha == "sha1"
    assert reloaded_run.repository_id == repository_id
    assert reloaded_run.branch_name == "main"
    assert reloaded_run.commit_sha == "sha1"
    assert reloaded_run.config_snapshot == {"max_commit_history": 200}
    assert reloaded_run.status == IngestionStatus.READY.value
    assert reloaded_run.result_profile == {"languages": {"Python": 500}}
    assert [r.id for r in runs_for_repo] == [run_id]


def test_multiple_analysis_runs_per_repository_are_all_retained(db_session):
    repository = upsert_repository(
        db_session,
        provider="github",
        owner="octocat",
        name="hello-world",
        source_url="https://github.com/octocat/hello-world",
    )
    run1 = create_analysis_run(db_session, repository, branch_name="main", commit_sha="sha1", config_snapshot={})
    fail_first = create_analysis_run(db_session, repository, branch_name="main", commit_sha="sha2", config_snapshot={})
    db_session.commit()

    runs = list_analysis_runs_for_repository(db_session, repository.id)
    assert {r.id for r in runs} == {run1.id, fail_first.id}
