from pathlib import Path

import pytest

from app.core.config import Settings
from app.domain.errors import RepositoryTooLargeError
from app.services.file_scanner import scan_file_tree


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "workspace")


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_finds_source_files(tmp_path, settings):
    repo = tmp_path / "repo"
    _write(repo / "src" / "main.py", "print('hi')")
    _write(repo / "README.md", "# hi")

    entries = scan_file_tree(repo, settings)
    paths = {e.relative_path for e in entries}
    assert "src/main.py" in paths
    assert "README.md" in paths

    main_entry = next(e for e in entries if e.relative_path == "src/main.py")
    assert main_entry.language == "Python"
    assert main_entry.category == "source"

    readme_entry = next(e for e in entries if e.relative_path == "README.md")
    assert readme_entry.category == "docs"


def test_always_excluded_dirs_skipped_even_without_gitignore(tmp_path, settings):
    repo = tmp_path / "repo"
    _write(repo / "node_modules" / "some_pkg" / "index.js", "module.exports = {}")
    _write(repo / "src" / "app.js", "console.log(1)")

    entries = scan_file_tree(repo, settings)
    paths = {e.relative_path for e in entries}
    assert "src/app.js" in paths
    assert not any(p.startswith("node_modules/") for p in paths)


def test_gitignore_negation_cannot_override_always_excluded_dirs(tmp_path, settings):
    repo = tmp_path / "repo"
    _write(repo / ".gitignore", "!node_modules/\n!node_modules/**\n")
    _write(repo / "node_modules" / "pkg" / "index.js", "x")

    entries = scan_file_tree(repo, settings)
    paths = {e.relative_path for e in entries}
    assert not any(p.startswith("node_modules/") for p in paths)


def test_gitignore_respected_for_normal_files(tmp_path, settings):
    repo = tmp_path / "repo"
    _write(repo / ".gitignore", "*.log\nbuild_output/\n")
    _write(repo / "app.py", "x")
    _write(repo / "debug.log", "x")
    _write(repo / "build_output" / "artifact.bin", "x")

    entries = scan_file_tree(repo, settings)
    paths = {e.relative_path for e in entries}
    assert "app.py" in paths
    assert "debug.log" not in paths
    assert not any(p.startswith("build_output/") for p in paths)


def test_symlinks_are_skipped(tmp_path, settings):
    repo = tmp_path / "repo"
    _write(repo / "real_file.py", "x")
    link_path = repo / "link_to_real.py"
    try:
        link_path.symlink_to(repo / "real_file.py")
    except OSError:
        pytest.skip("symlinks not supported in this environment")

    entries = scan_file_tree(repo, settings)
    paths = {e.relative_path for e in entries}
    assert "real_file.py" in paths
    assert "link_to_real.py" not in paths


def test_max_scan_file_count_enforced(tmp_path):
    repo = tmp_path / "repo"
    for i in range(5):
        _write(repo / f"file_{i}.py", "x")
    tight_settings = Settings(workspace_root=tmp_path / "workspace", max_scan_file_count=3)

    with pytest.raises(RepositoryTooLargeError):
        scan_file_tree(repo, tight_settings)


@pytest.mark.parametrize(
    "relative,expected_category",
    [
        ("requirements.txt", "dependency"),
        ("package.json", "dependency"),
        ("Makefile", "build"),
        ("Dockerfile", "build"),
        ("tests/test_foo.py", "test"),
        ("src/foo_test.py", "test"),
        ("README.md", "docs"),
        ("LICENSE", "docs"),
        ("tox.ini", "config"),
        (".gitignore", "config"),
        ("src/main.py", "source"),
        ("data/notes.xyz", "other"),
    ],
)
def test_file_categories(tmp_path, settings, relative, expected_category):
    repo = tmp_path / "repo"
    _write(repo / relative, "x")
    entries = scan_file_tree(repo, settings)
    entry = next(e for e in entries if e.relative_path == relative)
    assert entry.category == expected_category
