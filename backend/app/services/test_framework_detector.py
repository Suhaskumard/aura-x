"""
Test-framework detection.

Detects pytest/unittest/tox/nox/Jest/Vitest/Mocha via static file
presence and bounded content reads only. Never executes anything -- no
`pytest --version`, no `npm ls`, no invoking any tool the repository
ships. See app/services/clone_service.py for the one module allowed to
spawn a subprocess; this module deliberately isn't it.
"""

from __future__ import annotations

from pathlib import Path

from app.domain.models import FileEntry

_MAX_CONFIG_READ_BYTES = 1_000_000  # 1MB cap on config-file content reads

_PRESENCE_MARKERS: dict[str, tuple[str, ...]] = {
    "tox": ("tox.ini",),
    "nox": ("noxfile.py",),
}

_CONFIG_GLOB_MARKERS: dict[str, tuple[str, ...]] = {
    "jest": ("jest.config.js", "jest.config.ts", "jest.config.mjs", "jest.config.cjs", "jest.config.json"),
    "vitest": ("vitest.config.js", "vitest.config.ts", "vitest.config.mjs"),
    "mocha": (".mocharc.js", ".mocharc.json", ".mocharc.yml", ".mocharc.yaml"),
    "pytest": ("pytest.ini",),
}

_CONTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "pytest": ("[tool.pytest.ini_options]", "[pytest]", "pytest"),
    "jest": ('"jest"',),
    "vitest": ('"vitest"',),
    "mocha": ('"mocha"',),
}

_CONTENT_FILES = ("pyproject.toml", "tox.ini", "package.json")


def _read_bounded(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            raw = fh.read(_MAX_CONFIG_READ_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _read_requirements_files(local_path: Path) -> str:
    combined = ""
    for candidate in local_path.glob("requirements*.txt"):
        if candidate.is_file():
            combined += _read_bounded(candidate) + "\n"
    return combined


def detect_test_frameworks(local_path: Path, file_tree: list[FileEntry]) -> list[str]:
    detected: set[str] = set()
    names_present = {entry.relative_path.rsplit("/", 1)[-1].lower() for entry in file_tree}

    for framework, filenames in _PRESENCE_MARKERS.items():
        if any(name in names_present for name in filenames):
            detected.add(framework)

    for framework, filenames in _CONFIG_GLOB_MARKERS.items():
        if any(name in names_present for name in filenames):
            detected.add(framework)

    content = ""
    for filename in _CONTENT_FILES:
        candidate = local_path / filename
        if candidate.is_file():
            content += _read_bounded(candidate) + "\n"
    content += _read_requirements_files(local_path)
    content_lower = content.lower()

    for framework, markers in _CONTENT_MARKERS.items():
        if any(marker.lower() in content_lower for marker in markers):
            detected.add(framework)

    if "unittest" not in detected:
        # unittest is stdlib -- only worth flagging when test files exist
        # and reference it directly, since its presence can't be inferred
        # from a dependency/config file the way third-party frameworks can.
        for entry in file_tree:
            if entry.category == "test" and entry.extension == ".py":
                path = local_path / entry.relative_path
                text = _read_bounded(path)
                if "import unittest" in text or "from unittest" in text:
                    detected.add("unittest")
                    break

    return sorted(detected)
