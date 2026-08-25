from app.analysis.dependency_analysis import analyze
from app.domain.models import FileEntry
from app.domain.repository_context import RepositoryContext


def entry(path: str, category: str) -> FileEntry:
    return FileEntry(relative_path=path, extension="", size_bytes=1, category=category)


def make_context(**overrides) -> RepositoryContext:
    defaults = dict(
        repository_id="repo-1",
        provider="github",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        repository_name="hello-world",
        commit_sha="sha1",
    )
    defaults.update(overrides)
    return RepositoryContext(**defaults)


def test_analyze_without_local_path_returns_empty_report():
    context = make_context(local_path=None)
    report = analyze(context)

    assert report.dependencies == []
    assert report.dependency_count == 0
    assert report.ecosystems == []
    assert report.has_pinned_versions is False


def test_analyze_reads_requirements_and_detects_pinning(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi==0.115.6\npytest\n", encoding="utf-8")
    context = make_context(
        local_path=str(tmp_path), file_tree=[entry("requirements.txt", "dependency")]
    )
    report = analyze(context)

    assert set(report.dependencies) == {"fastapi", "pytest"}
    assert report.dependency_count == 2
    assert report.ecosystems == ["Python"]
    assert report.has_pinned_versions is True


def test_analyze_detects_multiple_ecosystems(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "1.0.0"}}', encoding="utf-8")
    context = make_context(
        local_path=str(tmp_path),
        file_tree=[entry("requirements.txt", "dependency"), entry("package.json", "dependency")],
    )
    report = analyze(context)

    assert report.ecosystems == ["JavaScript", "Python"]
    assert "react" in report.dependencies


def test_analyze_no_pinning_when_versions_unspecified(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
    context = make_context(local_path=str(tmp_path), file_tree=[entry("requirements.txt", "dependency")])
    report = analyze(context)
    assert report.has_pinned_versions is False


def test_analyze_carries_repository_id_and_commit_sha(tmp_path):
    context = make_context(repository_id="repo-xyz", commit_sha="deadbeef", local_path=str(tmp_path))
    report = analyze(context)
    assert report.repository_id == "repo-xyz"
    assert report.commit_sha == "deadbeef"
