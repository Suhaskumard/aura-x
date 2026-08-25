"""
Test-framework and test-directory detection (Phase 8).

Purely static: inspects file names, directory names, and manifest/config
file *contents* as text. Never imports, executes, or invokes pytest, npm,
or any test runner -- detection must not run arbitrary code from a
repository that hasn't been analyzed yet.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.domain.models import FileEntry

# Config-file presence is direct, unambiguous evidence of a framework.
_CONFIG_FILENAME_MARKERS: dict[str, str] = {
    "pytest.ini": "pytest",
    "tox.ini": "tox",
    "noxfile.py": "nox",
    "conftest.py": "pytest",
}
_CONFIG_PREFIX_MARKERS: dict[str, str] = {
    "jest.config": "Jest",
    "vitest.config": "Vitest",
    ".mocharc": "Mocha",
}

# npm package name -> framework, checked against package.json dependencies.
_NPM_PACKAGE_MARKERS: dict[str, str] = {
    "jest": "Jest",
    "vitest": "Vitest",
    "mocha": "Mocha",
}

# Section/keyword to look for inside a Python manifest's raw text (covers
# pytest/tox/nox declared as a dependency or configured under
# [tool.pytest.ini_options] / [tox] in pyproject.toml).
_PYTHON_MANIFEST_FILES = ("requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.cfg")
_PYTHON_MANIFEST_MARKERS: dict[str, str] = {
    "pytest": "pytest",
    "tox": "tox",
    "nox": "nox",
}

_TEST_DIR_NAMES = frozenset({"test", "tests", "__tests__", "spec", "specs"})


def _frameworks_from_file_tree(file_tree: list[FileEntry]) -> set[str]:
    frameworks: set[str] = set()
    for entry in file_tree:
        filename = entry.relative_path.rsplit("/", 1)[-1]
        if filename in _CONFIG_FILENAME_MARKERS:
            frameworks.add(_CONFIG_FILENAME_MARKERS[filename])
        for prefix, framework in _CONFIG_PREFIX_MARKERS.items():
            if filename.startswith(prefix):
                frameworks.add(framework)
    return frameworks


def _frameworks_from_package_json(root_path: Path) -> set[str]:
    package_json = root_path / "package.json"
    if not package_json.is_file():
        return set()
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return set()
    if not isinstance(payload, dict):
        return set()
    deps = {**(payload.get("dependencies") or {}), **(payload.get("devDependencies") or {})}
    return {framework for name, framework in _NPM_PACKAGE_MARKERS.items() if name in deps}


def _frameworks_from_python_manifests(root_path: Path) -> set[str]:
    frameworks: set[str] = set()
    for filename in _PYTHON_MANIFEST_FILES:
        candidate = root_path / filename
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for keyword, framework in _PYTHON_MANIFEST_MARKERS.items():
            if re.search(rf"\b{keyword}\b", text):
                frameworks.add(framework)
    return frameworks


def detect_test_frameworks(root: str | Path, file_tree: list[FileEntry]) -> list[str]:
    """Detect test frameworks with direct evidence only (a config file, or
    a declared dependency) -- never guesses a framework merely because
    `test_*.py`-shaped files exist, since that's equally consistent with
    plain stdlib `unittest`."""
    root_path = Path(root)
    frameworks = (
        _frameworks_from_file_tree(file_tree)
        | _frameworks_from_package_json(root_path)
        | _frameworks_from_python_manifests(root_path)
    )
    return sorted(frameworks)


def detect_test_directories(file_tree: list[FileEntry]) -> list[str]:
    """Directories (relative to the repo root) that contain at least one
    file whose path matches a conventional test-directory name."""
    directories: set[str] = set()
    for entry in file_tree:
        parts = entry.relative_path.split("/")[:-1]
        for depth, part in enumerate(parts):
            if part.lower() in _TEST_DIR_NAMES:
                directories.add("/".join(parts[: depth + 1]))
    return sorted(directories)
