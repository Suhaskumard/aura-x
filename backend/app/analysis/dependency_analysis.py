"""
Dependency Analysis (Phase 12): dependency inventory and a couple of
basic ecosystem/pinning signals, derived from RepositoryContext alone --
`context.local_path` and `context.file_tree` are both already on the
context (Phase 7/8), so reading the manifest files there isn't a
re-fetch or a re-derivation of anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.domain.repository_context import RepositoryContext
from app.services.dependency_scanner import extract_dependencies
from app.services.language_map import DEPENDENCY_FILE_LANGUAGE_MAP

_VERSION_PIN_MARKERS = ("==", ">=", "<=", "~=")


@dataclass(frozen=True, slots=True)
class DependencyAnalysisReport:
    repository_id: str
    commit_sha: str | None
    dependencies: list[str] = field(default_factory=list)
    dependency_count: int = 0
    ecosystems: list[str] = field(default_factory=list)
    has_pinned_versions: bool = False


def _ecosystems(file_tree) -> list[str]:
    names: set[str] = set()
    for entry in file_tree:
        if entry.category != "dependency":
            continue
        filename = entry.relative_path.rsplit("/", 1)[-1]
        language = DEPENDENCY_FILE_LANGUAGE_MAP.get(filename)
        if language:
            names.add(language)
    return sorted(names)


def _has_pinned_versions(root: Path) -> bool:
    candidate = root / "requirements.txt"
    if not candidate.is_file():
        return False
    try:
        text = candidate.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in text for marker in _VERSION_PIN_MARKERS)


def analyze(context: RepositoryContext) -> DependencyAnalysisReport:
    if context.local_path is None:
        return DependencyAnalysisReport(repository_id=context.repository_id, commit_sha=context.commit_sha)

    root = Path(context.local_path)
    dependencies = extract_dependencies(root)

    return DependencyAnalysisReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        dependencies=dependencies,
        dependency_count=len(dependencies),
        ecosystems=_ecosystems(context.file_tree),
        has_pinned_versions=_has_pinned_versions(root),
    )
