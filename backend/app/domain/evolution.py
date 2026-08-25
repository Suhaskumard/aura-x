"""
Evolution signal types (Phase 8): the churn/co-change/concentration data
computed from commit history that feeds the Risk Engine. Plain,
serializable dataclasses -- no provider or ORM types -- matching the rest
of app/domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FileChurnStat:
    path: str
    change_count: int
    additions: int
    deletions: int
    last_changed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CoChangePair:
    file_a: str
    file_b: str
    co_change_count: int


@dataclass(frozen=True, slots=True)
class EvolutionSignals:
    analyzed_commit_count: int
    file_churn: list[FileChurnStat] = field(default_factory=list)
    recently_changed_files: list[str] = field(default_factory=list)
    co_changes: list[CoChangePair] = field(default_factory=list)
    change_concentration: float = 0.0
