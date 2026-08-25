"""
Repository tree scanning (Phase 8).

Walks a cloned working tree on disk and builds the FileEntry inventory
that feeds RepositoryContext.file_tree. Read-only: never executes
anything in the scanned tree. Respects .gitignore, skips well-known
noise directories (.git, node_modules, virtualenvs, build/cache output),
and skips oversized or binary files.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from app.domain.models import FileEntry
from app.services.language_map import EXTENSION_LANGUAGE_MAP

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".nox",
        "dist",
        "build",
        ".next",
        ".cache",
        "vendor",
        "target",
        ".idea",
        ".vscode",
        "coverage",
        "htmlcov",
        ".eggs",
        ".workspace",
    }
)

BINARY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
        ".pdf", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar",
        ".exe", ".dll", ".so", ".dylib", ".class", ".jar",
        ".pyc", ".pyo", ".pyd",
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        ".mp3", ".mp4", ".mov", ".avi", ".wasm",
        ".db", ".sqlite", ".sqlite3",
    }
)

DEFAULT_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # oversized files are skipped, never truncated

_TEST_PATH_HINTS = ("test_", "_test.", ".test.", ".spec.", "__tests__/", "tests/", "test/", "spec/")
_DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt", ".adoc"})
_BUILD_DIR_HINTS = ("build/", "dist/", "target/", "out/")
_CONFIG_EXTENSIONS = frozenset({".toml", ".ini", ".cfg", ".yml", ".yaml"})
_CONFIG_FILENAMES = frozenset(
    {
        ".gitignore", ".gitattributes", ".editorconfig", "pyproject.toml", "setup.cfg",
        "tox.ini", "pytest.ini", "noxfile.py", "tsconfig.json", ".eslintrc", ".eslintrc.json",
        ".prettierrc", "dockerfile", "docker-compose.yml", "makefile",
        "webpack.config.js", "vite.config.ts", "vite.config.js",
        "jest.config.js", "jest.config.ts",
    }
)
_DEPENDENCY_FILENAMES = frozenset(
    {
        "requirements.txt", "requirements-dev.txt", "pipfile", "pipfile.lock", "poetry.lock",
        "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "pom.xml", "build.gradle", "build.gradle.kts", "cargo.toml", "cargo.lock",
        "go.mod", "go.sum", "gemfile", "gemfile.lock", "composer.json",
    }
)


def _load_gitignore_patterns(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def _matches_gitignore(relative_path: str, patterns: list[str]) -> bool:
    parts = relative_path.split("/")
    for raw_pattern in patterns:
        pattern = raw_pattern.rstrip("/")
        if not pattern:
            continue
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        if "/" not in pattern and any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def _looks_binary(path: Path, sniff_bytes: int = 8000) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def _categorize(relative_path: str, extension: str) -> str:
    lower = relative_path.lower()
    filename = lower.rsplit("/", 1)[-1]

    if any(hint in lower for hint in _TEST_PATH_HINTS):
        return "test"
    if filename in _DEPENDENCY_FILENAMES:
        return "dependency"
    if extension in _DOC_EXTENSIONS or lower.startswith("docs/") or "/docs/" in lower:
        return "docs"
    if any(lower.startswith(hint) or f"/{hint}" in lower for hint in _BUILD_DIR_HINTS):
        return "build"
    if filename in _CONFIG_FILENAMES or extension in _CONFIG_EXTENSIONS:
        return "config"
    if extension in EXTENSION_LANGUAGE_MAP:
        return "source"
    return "other"


def scan_repository_tree(
    root: str | Path,
    *,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS,
) -> list[FileEntry]:
    """Build the file inventory for a cloned repository at `root`.

    Excludes `.git` and other well-known noise directories, anything
    matched by the repo's own top-level `.gitignore`, and any file that is
    oversized (`max_file_size_bytes`) or looks binary (null byte in the
    first few KB, or a known binary extension). Symlinks are skipped so a
    malicious repo can't point one outside the workspace.
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        return []

    gitignore_patterns = _load_gitignore_patterns(root_path)
    entries: list[FileEntry] = []

    for path in sorted(root_path.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue

        relative = path.relative_to(root_path)
        parts = relative.parts
        if any(part in excluded_dirs for part in parts[:-1]):
            continue

        relative_str = relative.as_posix()
        if _matches_gitignore(relative_str, gitignore_patterns):
            continue

        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        if size_bytes > max_file_size_bytes:
            continue

        extension = path.suffix.lower()
        if extension in BINARY_EXTENSIONS:
            continue
        if size_bytes > 0 and _looks_binary(path):
            continue

        entries.append(
            FileEntry(
                relative_path=relative_str,
                extension=extension,
                size_bytes=size_bytes,
                category=_categorize(relative_str, extension),
                language=EXTENSION_LANGUAGE_MAP.get(extension),
            )
        )

    return entries
