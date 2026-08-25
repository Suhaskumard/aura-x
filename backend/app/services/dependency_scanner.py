"""
Static dependency-name extraction (Phase 8) for the Repository Profile
view. Reads known manifest files at the repository root as plain text --
never invokes pip, npm, or any package manager.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_VERSION_SPLIT_RE = re.compile(r"[<>=!~;\[\s]")


def _parse_requirements_txt(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    names: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = _VERSION_SPLIT_RE.split(line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def _parse_package_json(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    names: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        section = payload.get(key)
        if isinstance(section, dict):
            names.update(section.keys())
    return sorted(names)


_MANIFEST_PARSERS = {
    "requirements.txt": _parse_requirements_txt,
    "requirements-dev.txt": _parse_requirements_txt,
    "package.json": _parse_package_json,
}


def extract_dependencies(root: str | Path) -> list[str]:
    """Best-effort dependency-name list from manifest files at the
    repository root. Not exhaustive (doesn't resolve lockfiles or
    transitive dependencies) -- good enough for the Repository Profile
    summary; the Risk/Evolution engines consume file_tree/git history, not
    this list."""
    root_path = Path(root)
    names: set[str] = set()
    for filename, parser in _MANIFEST_PARSERS.items():
        candidate = root_path / filename
        if candidate.is_file():
            names.update(parser(candidate))
    return sorted(names)
