"""
Phase 8 orchestration: turn a Phase-7-cloned workspace into the four
pieces RepositoryContext needs -- file tree, languages, test frameworks,
and evolution signals. The future Phase 11 orchestrator applies these
directly onto a RepositoryContext instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings
from app.domain.models import EvolutionSignals, FileEntry
from app.services import evolution_analyzer, file_scanner, test_framework_detector
from app.services.language_detector import resolve_languages


@dataclass(frozen=True, slots=True)
class ScanResult:
    file_tree: list[FileEntry]
    languages: dict[str, int]
    test_frameworks: list[str]
    evolution_signals: EvolutionSignals


def _aggregate_local_language_bytes(file_tree: list[FileEntry]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for entry in file_tree:
        if entry.language is None:
            continue
        totals[entry.language] = totals.get(entry.language, 0) + entry.size_bytes
    return totals


def scan_repository(
    *,
    local_path: Path,
    github_languages: dict[str, int],
    settings: Settings | None = None,
) -> ScanResult:
    settings = settings or get_settings()

    file_tree = file_scanner.scan_file_tree(local_path, settings)
    local_totals = _aggregate_local_language_bytes(file_tree)
    languages = resolve_languages(local_scan_totals=local_totals, github_languages=github_languages)
    test_frameworks = test_framework_detector.detect_test_frameworks(local_path, file_tree)
    signals = evolution_analyzer.analyze_evolution(local_path, settings)

    return ScanResult(
        file_tree=file_tree,
        languages=languages,
        test_frameworks=test_frameworks,
        evolution_signals=signals,
    )
