"""
Git evolution signal computation (Phase 8): file churn, modification
frequency, recently changed files, co-changing files, and change
concentration -- derived from commit history so the Risk Engine has
real signal about which files are hot / tightly coupled.

Pure function over `list[CommitInfo]`: no I/O, no provider dependency.
Commits are expected newest-first (the order GitHub's commit-list API and
CommitInfo already use) and to have `changed_files` populated for at
least the most recent ones -- see
app/services/repository_service.py::enrich_commit_history, which fetches
that per-commit data (not included in the bulk commit-history listing)
for a bounded window before calling this function.
"""

from __future__ import annotations

from itertools import combinations

from app.domain.evolution import CoChangePair, EvolutionSignals, FileChurnStat
from app.domain.models import CommitInfo

DEFAULT_RECENT_FILE_LIMIT = 20
DEFAULT_CO_CHANGE_TOP_N = 20
DEFAULT_CONCENTRATION_TOP_FRACTION = 0.2


def compute_evolution_signals(
    commits: list[CommitInfo],
    *,
    recent_file_limit: int = DEFAULT_RECENT_FILE_LIMIT,
    co_change_top_n: int = DEFAULT_CO_CHANGE_TOP_N,
    concentration_top_fraction: float = DEFAULT_CONCENTRATION_TOP_FRACTION,
) -> EvolutionSignals:
    file_stats: dict[str, dict] = {}
    co_change_counts: dict[tuple[str, str], int] = {}
    recently_changed: list[str] = []
    seen: set[str] = set()

    for commit in commits:
        paths = [change.path for change in commit.changed_files if change.path]

        for change in commit.changed_files:
            if not change.path:
                continue
            stat = file_stats.setdefault(
                change.path, {"count": 0, "additions": 0, "deletions": 0, "last_changed_at": None}
            )
            stat["count"] += 1
            stat["additions"] += change.additions
            stat["deletions"] += change.deletions
            if commit.committed_at is not None and (
                stat["last_changed_at"] is None or commit.committed_at > stat["last_changed_at"]
            ):
                stat["last_changed_at"] = commit.committed_at

        for path in paths:
            if path not in seen:
                seen.add(path)
                recently_changed.append(path)

        for file_a, file_b in combinations(sorted(set(paths)), 2):
            key = (file_a, file_b)
            co_change_counts[key] = co_change_counts.get(key, 0) + 1

    file_churn = sorted(
        (
            FileChurnStat(
                path=path,
                change_count=stat["count"],
                additions=stat["additions"],
                deletions=stat["deletions"],
                last_changed_at=stat["last_changed_at"],
            )
            for path, stat in file_stats.items()
        ),
        key=lambda s: (-s.change_count, s.path),
    )

    co_changes = sorted(
        (
            CoChangePair(file_a=file_a, file_b=file_b, co_change_count=count)
            for (file_a, file_b), count in co_change_counts.items()
            if count > 1
        ),
        key=lambda pair: (-pair.co_change_count, pair.file_a, pair.file_b),
    )[:co_change_top_n]

    total_churn = sum(stat.change_count for stat in file_churn)
    if total_churn and file_churn:
        top_n = max(1, round(len(file_churn) * concentration_top_fraction))
        top_churn = sum(stat.change_count for stat in file_churn[:top_n])
        change_concentration = round(top_churn / total_churn, 4)
    else:
        change_concentration = 0.0

    return EvolutionSignals(
        analyzed_commit_count=len(commits),
        file_churn=file_churn,
        recently_changed_files=recently_changed[:recent_file_limit],
        co_changes=co_changes,
        change_concentration=change_concentration,
    )
