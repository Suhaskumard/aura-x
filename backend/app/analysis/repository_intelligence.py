"""
Repository Intelligence (Phase 12): a structural/analytical summary of a
repository, derived entirely from an already-assembled RepositoryContext
(Phase 8's file_tree/languages/test_frameworks) -- no filesystem re-scan,
no re-fetch from GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.repository_context import RepositoryContext

# File-count thresholds for size_classification -- a simple, documented
# heuristic (not lines-of-code, which file_tree doesn't carry), good
# enough to distinguish "a script" from "a real project" from "a monorepo".
_SMALL_MAX_FILES = 50
_MEDIUM_MAX_FILES = 500


@dataclass(frozen=True, slots=True)
class LanguageBreakdownEntry:
    language: str
    bytes: int
    percentage: float


@dataclass(frozen=True, slots=True)
class RepositoryIntelligenceReport:
    repository_id: str
    commit_sha: str | None
    primary_language: str | None
    language_breakdown: list[LanguageBreakdownEntry] = field(default_factory=list)
    total_files: int = 0
    total_size_bytes: int = 0
    files_by_category: dict[str, int] = field(default_factory=dict)
    size_classification: str = "unknown"  # "small" | "medium" | "large" | "unknown"
    has_readme: bool = False
    has_test_directory: bool = False
    test_framework_count: int = 0
    top_level_directories: list[str] = field(default_factory=list)


def _size_classification(total_files: int) -> str:
    if total_files == 0:
        return "unknown"
    if total_files <= _SMALL_MAX_FILES:
        return "small"
    if total_files <= _MEDIUM_MAX_FILES:
        return "medium"
    return "large"


def _language_breakdown(languages: dict[str, int]) -> list[LanguageBreakdownEntry]:
    total = sum(languages.values())
    if total == 0:
        return [LanguageBreakdownEntry(language=name, bytes=0, percentage=0.0) for name in languages]
    return [
        LanguageBreakdownEntry(language=name, bytes=count, percentage=round(100 * count / total, 2))
        for name, count in languages.items()
    ]


def analyze(context: RepositoryContext) -> RepositoryIntelligenceReport:
    file_tree = context.file_tree

    files_by_category: dict[str, int] = {}
    top_level_dirs: set[str] = set()
    has_readme = False
    has_test_directory = False

    for entry in file_tree:
        files_by_category[entry.category] = files_by_category.get(entry.category, 0) + 1
        if entry.category == "test":
            has_test_directory = True
        parts = entry.relative_path.split("/")
        if len(parts) > 1:
            top_level_dirs.add(parts[0])
        elif parts[0].lower().startswith("readme"):
            has_readme = True

    total_size_bytes = sum(entry.size_bytes for entry in file_tree)
    primary_language = next(iter(context.languages), None) if context.languages else None
    # languages is already sorted by descending bytes (see
    # app/services/language_detector.py::detect_languages), so the first
    # key is the primary language -- no need to re-sort here.

    return RepositoryIntelligenceReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        primary_language=primary_language,
        language_breakdown=_language_breakdown(context.languages),
        total_files=len(file_tree),
        total_size_bytes=total_size_bytes,
        files_by_category=files_by_category,
        size_classification=_size_classification(len(file_tree)),
        has_readme=has_readme,
        has_test_directory=has_test_directory,
        test_framework_count=len(context.test_frameworks),
        top_level_directories=sorted(top_level_dirs),
    )
