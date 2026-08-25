"""
Evolution Analysis (Phase 12): interprets the churn/co-change/
concentration signals app/services/evolution_analysis.py already computed
(Phase 8, stored on RepositoryContext.evolution_signals) into a downstream
report -- hotspot files, tightly-coupled file pairs, and a churn-pattern
read. This module deliberately does no signal computation itself; it only
consumes what Phase 8 already produced, per this phase's exit criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.repository_context import RepositoryContext

_TOP_N = 10
_CONCENTRATED_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class HotspotFile:
    path: str
    change_count: int
    last_changed_at: datetime | None


@dataclass(frozen=True, slots=True)
class CouplingRisk:
    file_a: str
    file_b: str
    co_change_count: int


@dataclass(frozen=True, slots=True)
class EvolutionInsightsReport:
    repository_id: str
    commit_sha: str | None
    analyzed_commit_count: int = 0
    hotspot_files: list[HotspotFile] = field(default_factory=list)
    tightly_coupled_pairs: list[CouplingRisk] = field(default_factory=list)
    change_concentration: float = 0.0
    # "unknown" (no signals computed), "none" (signals present but no
    # churn observed), "concentrated" (most churn in a few hotspot
    # files), or "distributed" (churn spread across many files).
    churn_pattern: str = "unknown"


def _churn_pattern(hotspot_count: int, change_concentration: float) -> str:
    if hotspot_count == 0:
        return "none"
    if change_concentration >= _CONCENTRATED_THRESHOLD:
        return "concentrated"
    return "distributed"


def analyze(context: RepositoryContext) -> EvolutionInsightsReport:
    signals = context.evolution_signals
    if signals is None:
        return EvolutionInsightsReport(repository_id=context.repository_id, commit_sha=context.commit_sha)

    hotspots = [
        HotspotFile(path=stat.path, change_count=stat.change_count, last_changed_at=stat.last_changed_at)
        for stat in signals.file_churn[:_TOP_N]
    ]
    coupling = [
        CouplingRisk(file_a=pair.file_a, file_b=pair.file_b, co_change_count=pair.co_change_count)
        for pair in signals.co_changes[:_TOP_N]
    ]

    return EvolutionInsightsReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        analyzed_commit_count=signals.analyzed_commit_count,
        hotspot_files=hotspots,
        tightly_coupled_pairs=coupling,
        change_concentration=signals.change_concentration,
        churn_pattern=_churn_pattern(len(hotspots), signals.change_concentration),
    )
