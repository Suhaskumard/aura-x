"""
Repository file-tree scanning.

Walks a cloned workspace directory (Phase 7's CloneResult.local_path) and
produces a bounded, deterministic inventory of FileEntry objects.
Respects the repository's own .gitignore via `pathspec`, but a fixed set
of directories is excluded unconditionally regardless of .gitignore
content -- a repo's own `!node_modules/` negation can't defeat these,
since they exist to keep the scan itself fast and safe, not to mirror
git's notion of tracked files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pathspec

from app.core.config import Settings, get_settings
from app.domain.errors import RepositoryTooLargeError
from app.domain.models import FileEntry
from app.services.language_detector import detect_language

_ALWAYS_EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", "venv", ".venv", "__pycache__", ".cache", "build", "dist", "coverage"}
)

_TEST_PATH_MARKERS = ("test", "tests", "spec", "specs", "__tests__")
_DOC_EXTENSIONS = frozenset({".md", ".rst", ".txt"})
_DOC_BASENAMES = frozenset({"readme", "changelog", "license", "contributing"})
_DEPENDENCY_FILENAMES = frozenset(
    {
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "poetry.lock",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "gemfile",
        "gemfile.lock",
        "composer.json",
        "composer.lock",
    }
)
_BUILD_FILENAMES = frozenset({"makefile", "dockerfile", "docker-compose.yml", "docker-compose.yaml"})
_CONFIG_EXTENSIONS = frozenset({".ini", ".cfg", ".env"})
_CONFIG_FILENAMES = frozenset({".gitignore", ".editorconfig", ".flake8", "tox.ini", "pytest.ini", "noxfile.py"})


def _load_gitignore_spec(local_path: Path) -> pathspec.PathSpec:
    gitignore_path = local_path / ".gitignore"
    if not gitignore_path.is_file():
        return pathspec.PathSpec.from_lines("gitwildmatch", [])
    lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _classify_file(relative: Path, extension: str) -> str:
    name_lower = relative.name.lower()
    parts_lower = {p.lower() for p in relative.parts}
    stem_lower = relative.stem.lower()
    posix_lower = relative.as_posix().lower()

    if name_lower in _DEPENDENCY_FILENAMES:
        return "dependency"
    if name_lower in _BUILD_FILENAMES or ".github/workflows" in posix_lower:
        return "build"
    if (
        any(marker in parts_lower for marker in _TEST_PATH_MARKERS)
        or name_lower.startswith("test_")
        or name_lower.endswith("_test.py")
        or name_lower.endswith(".test.js")
        or name_lower.endswith(".test.ts")
        or name_lower.endswith(".spec.js")
        or name_lower.endswith(".spec.ts")
    ):
        return "test"
    if extension in _DOC_EXTENSIONS or stem_lower in _DOC_BASENAMES:
        return "docs"
    if name_lower in _CONFIG_FILENAMES or extension in _CONFIG_EXTENSIONS:
        return "config"
    if detect_language(extension) is not None:
        return "source"
    return "other"


def scan_file_tree(local_path: Path, settings: Settings | None = None) -> list[FileEntry]:
    settings = settings or get_settings()
    spec = _load_gitignore_spec(local_path)
    entries: list[FileEntry] = []

    for root, dirnames, filenames in os.walk(local_path):
        root_path = Path(root)
        # Prune in place so os.walk never descends into an excluded or
        # gitignored directory -- avoids walking huge node_modules/.git
        # trees just to discard everything found there.
        kept_dirnames = []
        for dirname in dirnames:
            if dirname in _ALWAYS_EXCLUDED_DIRS:
                continue
            rel_dir = (root_path / dirname).relative_to(local_path).as_posix()
            if spec.match_file(rel_dir + "/"):
                continue
            kept_dirnames.append(dirname)
        dirnames[:] = sorted(kept_dirnames)

        for filename in sorted(filenames):
            file_path = root_path / filename
            if file_path.is_symlink() or not file_path.is_file():
                continue

            relative = file_path.relative_to(local_path)
            rel_posix = relative.as_posix()
            if spec.match_file(rel_posix):
                continue

            if len(entries) >= settings.max_scan_file_count:
                raise RepositoryTooLargeError(
                    f"Repository exceeds the max scanned file count of {settings.max_scan_file_count}"
                )

            extension = file_path.suffix.lower()
            entries.append(
                FileEntry(
                    relative_path=rel_posix,
                    extension=extension,
                    size_bytes=file_path.lstat().st_size,
                    category=_classify_file(relative, extension),
                    language=detect_language(extension),
                )
            )

    return entries
