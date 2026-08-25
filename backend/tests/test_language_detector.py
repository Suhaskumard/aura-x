from app.domain.models import FileEntry
from app.services.language_detector import detect_languages


def entry(path: str, size: int, language: str | None) -> FileEntry:
    return FileEntry(
        relative_path=path,
        extension="." + path.rsplit(".", 1)[-1] if "." in path else "",
        size_bytes=size,
        category="source",
        language=language,
    )


def test_github_counts_are_used_as_starting_point():
    file_tree: list[FileEntry] = []
    result = detect_languages(file_tree, {"Python": 5000, "HTML": 200})
    assert result == {"Python": 5000, "HTML": 200}


def test_file_tree_sizes_are_added_to_github_counts():
    file_tree = [entry("app/main.py", 100, "Python")]
    result = detect_languages(file_tree, {"Python": 5000})
    assert result["Python"] == 5100


def test_extension_fallback_used_when_no_github_data():
    file_tree = [
        entry("app/main.py", 100, "Python"),
        entry("app/util.py", 50, "Python"),
        entry("web/index.html", 30, "HTML"),
    ]
    result = detect_languages(file_tree, {})
    assert result["Python"] == 150
    assert result["HTML"] == 30


def test_files_without_known_language_are_ignored():
    file_tree = [entry("data.bin", 999, None)]
    result = detect_languages(file_tree, {})
    assert result == {}


def test_dependency_manifest_adds_zero_count_language_when_absent():
    file_tree = [entry("requirements.txt", 20, None)]
    result = detect_languages(file_tree, {})
    assert result["Python"] == 0


def test_dependency_manifest_does_not_override_existing_count():
    file_tree = [
        entry("requirements.txt", 20, None),
        entry("app/main.py", 500, "Python"),
    ]
    result = detect_languages(file_tree, {})
    assert result["Python"] == 500


def test_result_sorted_by_descending_byte_count():
    file_tree = [
        entry("a.py", 10, "Python"),
        entry("b.js", 100, "JavaScript"),
    ]
    result = detect_languages(file_tree, {})
    assert list(result.keys()) == ["JavaScript", "Python"]
