from app.analysis.repository_intelligence import analyze
from app.domain.models import FileEntry
from app.domain.repository_context import RepositoryContext


def entry(path: str, size: int, category: str) -> FileEntry:
    extension = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    return FileEntry(relative_path=path, extension=extension, size_bytes=size, category=category)


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


def test_analyze_computes_language_breakdown_and_primary_language():
    context = make_context(languages={"Python": 800, "HTML": 200})
    report = analyze(context)

    assert report.primary_language == "Python"
    breakdown = {b.language: b.percentage for b in report.language_breakdown}
    assert breakdown["Python"] == 80.0
    assert breakdown["HTML"] == 20.0


def test_analyze_counts_files_by_category_and_total_size():
    context = make_context(
        file_tree=[
            entry("app/main.py", 100, "source"),
            entry("tests/test_main.py", 50, "test"),
            entry("README.md", 10, "docs"),
        ]
    )
    report = analyze(context)

    assert report.total_files == 3
    assert report.total_size_bytes == 160
    assert report.files_by_category == {"source": 1, "test": 1, "docs": 1}


def test_analyze_detects_readme_and_test_directory():
    context = make_context(
        file_tree=[entry("README.md", 10, "docs"), entry("tests/test_main.py", 50, "test")]
    )
    report = analyze(context)

    assert report.has_readme is True
    assert report.has_test_directory is True


def test_analyze_no_readme_or_tests():
    context = make_context(file_tree=[entry("app/main.py", 100, "source")])
    report = analyze(context)

    assert report.has_readme is False
    assert report.has_test_directory is False


def test_analyze_top_level_directories():
    context = make_context(
        file_tree=[
            entry("app/main.py", 10, "source"),
            entry("app/util.py", 10, "source"),
            entry("tests/test_main.py", 10, "test"),
            entry("setup.py", 10, "config"),
        ]
    )
    report = analyze(context)
    assert report.top_level_directories == ["app", "tests"]


def test_size_classification_thresholds():
    small = make_context(file_tree=[entry(f"f{i}.py", 1, "source") for i in range(10)])
    medium = make_context(file_tree=[entry(f"f{i}.py", 1, "source") for i in range(100)])
    large = make_context(file_tree=[entry(f"f{i}.py", 1, "source") for i in range(600)])
    empty = make_context(file_tree=[])

    assert analyze(small).size_classification == "small"
    assert analyze(medium).size_classification == "medium"
    assert analyze(large).size_classification == "large"
    assert analyze(empty).size_classification == "unknown"


def test_analyze_carries_repository_id_and_commit_sha():
    context = make_context(repository_id="repo-xyz", commit_sha="deadbeef")
    report = analyze(context)
    assert report.repository_id == "repo-xyz"
    assert report.commit_sha == "deadbeef"


def test_test_framework_count_reflects_context():
    context = make_context(test_frameworks=["pytest", "tox"])
    report = analyze(context)
    assert report.test_framework_count == 2
