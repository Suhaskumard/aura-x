"""
Git evolution/churn signal analysis.

Never spawns a subprocess directly -- delegates to
app.services.clone_service (the only module allowed to do that) for the
local `git fetch --deepen` and `git log --numstat` calls, then parses the
result here.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.domain.models import EvolutionSignals
from app.services import clone_service

# Commits touching more files than this are skipped for co-change pairing
# (but still counted toward file_churn) -- a large refactor/merge commit
# touching hundreds of files would otherwise generate O(n^2) pairs for no
# meaningful co-change signal.
_MAX_FILES_PER_COMMIT_FOR_COCHANGE = 50


def _parse_numstat_log(raw_log: str) -> EvolutionSignals:
    commits_analyzed = 0
    file_churn: dict[str, int] = {}
    co_change_counts: dict[tuple[str, str], int] = {}

    blocks = [block for block in raw_log.split("\x00") if block.strip()]

    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        commits_analyzed += 1

        files_in_commit: list[str] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added_str, removed_str, path = parts
            files_in_commit.append(path)
            if added_str == "-" or removed_str == "-":
                continue  # binary file, no line-based churn
            try:
                churn = int(added_str) + int(removed_str)
            except ValueError:
                continue
            file_churn[path] = file_churn.get(path, 0) + churn

        if len(files_in_commit) <= _MAX_FILES_PER_COMMIT_FOR_COCHANGE:
            for i in range(len(files_in_commit)):
                for j in range(i + 1, len(files_in_commit)):
                    pair = tuple(sorted((files_in_commit[i], files_in_commit[j])))
                    co_change_counts[pair] = co_change_counts.get(pair, 0) + 1

    return EvolutionSignals(
        commits_analyzed=commits_analyzed,
        file_churn=file_churn,
        co_change_counts=co_change_counts,
    )


def analyze_evolution(local_path: Path, settings: Settings | None = None) -> EvolutionSignals:
    settings = settings or get_settings()
    clone_service.deepen_for_history(local_path, settings)
    raw_log = clone_service.read_local_git_log(local_path, settings)
    return _parse_numstat_log(raw_log)
