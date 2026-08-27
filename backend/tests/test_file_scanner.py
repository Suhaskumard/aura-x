import os
import sys
from pathlib import Path

import pytest

from app.services.file_scanner import scan_repository_tree


def _write(root: Path, relative: str, content: str = "x") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_scan_builds_file_entries_with_category_and_language(tmp_path):
    _write(tmp_path, "app/main.py", "print('hi')\n")
    _write(tmp_path, "tests/test_main.py", "def test_x(): pass\n")
    _write(tmp_path, "README.md", "# Title\n")
    _write(tmp_path, "requirements.txt", "fastapi\n")
    _write(tmp_path, "pyproject.toml", "[tool.pytest]\n")

    entries = scan_repository_tree(tmp_path)
    by_path = {e.relative_path: e for e in entries}

    assert by_path["app/main.py"].category == "source"
    assert by_path["app/main.py"].language == "Python"
    assert by_path["tests/test_main.py"].category == "test"
    assert by_path["README.md"].category == "docs"
    assert by_path["requirements.txt"].category == "dependency"
    assert by_path["pyproject.toml"].category == "config"


def test_scan_excludes_noise_directories(tmp_path):
    _write(tmp_path, ".git/HEAD", "ref: refs/heads/main\n")
    _write(tmp_path, "node_modules/lib/index.js", "module.exports = {};\n")
    _write(tmp_path, "__pycache__/main.cpython-311.pyc", "x")
    _write(tmp_path, "app/main.py", "print(1)\n")

    entries = scan_repository_tree(tmp_path)
    paths = {e.relative_path for e in entries}

    assert paths == {"app/main.py"}


def test_scan_respects_gitignore(tmp_path):
    _write(tmp_path, ".gitignore", "*.log\nbuild_output/\n")
    _write(tmp_path, "app.log", "boom\n")
    _write(tmp_path, "build_output/artifact.txt", "binary-ish\n")
    _write(tmp_path, "app/main.py", "print(1)\n")

    entries = scan_repository_tree(tmp_path)
    paths = {e.relative_path for e in entries}

    assert "app.log" not in paths
    assert "build_output/artifact.txt" not in paths
    assert "app/main.py" in paths


def test_scan_skips_oversized_files(tmp_path):
    _write(tmp_path, "small.py", "x = 1\n")
    big = tmp_path / "big.py"
    big.write_bytes(b"a" * 1024)

    entries = scan_repository_tree(tmp_path, max_file_size_bytes=100)
    paths = {e.relative_path for e in entries}

    assert "small.py" in paths
    assert "big.py" not in paths


def test_scan_skips_binary_content(tmp_path):
    binary = tmp_path / "data.bin"
    binary.write_bytes(b"\x00\x01\x02binary")
    _write(tmp_path, "app/main.py", "print(1)\n")

    entries = scan_repository_tree(tmp_path)
    paths = {e.relative_path for e in entries}

    assert "data.bin" not in paths
    assert "app/main.py" in paths


def test_scan_skips_known_binary_extensions_without_sniffing(tmp_path):
    (tmp_path / "logo.png").write_bytes(b"not-really-png-but-extension-based-skip")

    entries = scan_repository_tree(tmp_path)
    assert entries == []


def test_scan_nonexistent_root_returns_empty_list(tmp_path):
    entries = scan_repository_tree(tmp_path / "does-not-exist")
    assert entries == []


def test_scan_is_deterministically_sorted(tmp_path):
    _write(tmp_path, "b.py", "1\n")
    _write(tmp_path, "a.py", "1\n")

    entries = scan_repository_tree(tmp_path)
    assert [e.relative_path for e in entries] == ["a.py", "b.py"]


def _mkdir_long(path: Path) -> None:
    r"""Create `path` and its parents even past Windows' default ~260-char
    MAX_PATH. `Path.mkdir(parents=True)` and `os.makedirs` both mishandle
    the `\\?\` extended-length prefix when given the full path in one
    call (they split it back apart internally), so build it one level at
    a time instead -- the same workaround `_long_path_safe()` in
    file_scanner.py documents on the read side."""
    if sys.platform != "win32":
        path.mkdir(parents=True, exist_ok=True)
        return
    current = path.drive + path.root
    for part in path.parts[1:]:
        current = os.path.join(current, part)
        try:
            os.mkdir("\\\\?\\" + current)
        except FileExistsError:
            pass


def test_scan_finds_files_past_windows_max_path(tmp_path):
    """A real cloned repository can easily nest deeper than Windows'
    default 260-character MAX_PATH (Java/Kotlin package trees, JS
    toolchain output, generated code -- more so once workspace_root's own
    path is long, e.g. under a synced folder). Without _long_path_safe(),
    Path.rglob() silently enumerates nothing for a subtree that deep: no
    exception, no partial-scan indicator, just files missing from every
    downstream result (language stats, dependencies, profile)."""
    deep = tmp_path
    while len(str(deep)) < 250:
        deep = deep / ("segment_" + "0123456789" * 2)
    try:
        _mkdir_long(deep)
    except OSError as exc:
        pytest.skip(f"this environment does not support long paths: {exc}")

    marker = deep / "deep_marker.py"
    if sys.platform == "win32":
        with open("\\\\?\\" + str(marker), "w", encoding="utf-8") as f:
            f.write("print(1)\n")
    else:
        marker.write_text("print(1)\n", encoding="utf-8")

    entries = scan_repository_tree(tmp_path)
    assert any(e.relative_path.endswith("deep_marker.py") for e in entries)
