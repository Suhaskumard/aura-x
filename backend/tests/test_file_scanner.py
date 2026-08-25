from pathlib import Path

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
