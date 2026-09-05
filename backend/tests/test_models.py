from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from app.domain.models import BranchInfo, CloneResult, CommitInfo, FileEntry, RepositoryMetadata


def make_metadata(**overrides) -> RepositoryMetadata:
    defaults = dict(
        repository_id="1",
        name="hello-world",
        owner="octocat",
        description=None,
        default_branch="main",
        visibility="public",
        primary_language="Python",
    )
    defaults.update(overrides)
    return RepositoryMetadata(**defaults)


@pytest.mark.parametrize(
    "factory,attr",
    [
        (lambda: make_metadata(), "name"),
        (lambda: BranchInfo(name="main", head_commit_sha="abc"), "name"),
        (
            lambda: CommitInfo(
                sha="abc", parents=[], author_name=None, author_email=None,
                committed_at=None, message="msg",
            ),
            "sha",
        ),
        (
            lambda: FileEntry(relative_path="a.py", extension=".py", size_bytes=1, category="source"),
            "relative_path",
        ),
        (
            lambda: CloneResult(
                local_path="/tmp/x", commit_sha="abc", branch="main",
                cloned_at=datetime.now(timezone.utc),
            ),
            "local_path",
        ),
    ],
)
def test_dataclasses_are_frozen(factory, attr):
    instance = factory()
    with pytest.raises(FrozenInstanceError):
        setattr(instance, attr, "changed")


def test_repository_metadata_topics_default_factory_not_shared():
    a = make_metadata()
    b = make_metadata()
    assert a.topics == []
    assert a.topics is not b.topics


def test_commit_info_changed_files_default_factory_not_shared():
    a = CommitInfo(
        sha="a", parents=[], author_name=None, author_email=None,
        committed_at=None, message="m",
    )
    b = CommitInfo(
        sha="b", parents=[], author_name=None, author_email=None,
        committed_at=None, message="m",
    )
    assert a.changed_files == []
    assert a.changed_files is not b.changed_files


def test_branch_info_is_default_defaults_false():
    branch = BranchInfo(name="feature", head_commit_sha="abc")
    assert branch.is_default is False


def test_repository_metadata_equality_by_value():
    a = make_metadata()
    b = make_metadata()
    assert a == b


def test_repository_metadata_is_unhashable_due_to_mutable_list_field():
    # Finding: RepositoryMetadata is declared frozen=True (implying it should
    # be usable as a dict key / set member like other frozen dataclasses),
    # but its `topics: list[str]` field makes the generated __hash__ raise
    # TypeError at call time. Frozen only prevents attribute *reassignment*;
    # it does not deep-freeze the list, so `metadata.topics.append(...)`
    # would also silently succeed despite the object claiming to be frozen.
    # Captured as a known gap rather than "fixed" since topics is typed and
    # consumed as list[str] elsewhere (app/services/github_provider.py).
    metadata = make_metadata()
    with pytest.raises(TypeError):
        hash(metadata)
    metadata.topics.append("mutated-despite-frozen")
    assert metadata.topics == ["mutated-despite-frozen"]


def test_repository_metadata_unicode_and_large_values():
    metadata = make_metadata(
        name="日本語" * 100,
        description="\U0001F600" * 500,
        topics=["éèê"] * 50,
    )
    assert len(metadata.name) == 300
    assert metadata.topics[0] == "éèê"


def test_file_entry_optional_language_defaults_none():
    entry = FileEntry(relative_path="a.txt", extension=".txt", size_bytes=0, category="other")
    assert entry.language is None
