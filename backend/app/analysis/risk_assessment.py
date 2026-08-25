"""
Risk Assessment (Phase 12): combines Phase 8's file-churn signals with a
static "does this source file appear to have an associated test" heuristic
to flag files that change often and appear untested -- the classic churn
x coverage risk read. Consumes RepositoryContext (file_tree,
evolution_signals) only; never executes anything or runs a real coverage
tool (there is no test execution anywhere in this pipeline).

The "has an associated test" check is a filename-stem heuristic (does any
test-category file's stem contain this source file's stem), not real
coverage data -- documented as such; good enough to flag "no test file
even exists for this" without executing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.domain.repository_context import RepositoryContext

# A source file changed at least this many times (within the analyzed
# commit window) counts as "high churn" for risk purposes -- a simple,
# documented threshold, not a statistically derived one.
_HIGH_CHURN_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class RiskItem:
    path: str
    change_count: int
    has_associated_test: bool
    risk_level: str  # "high" | "medium" | "low"


@dataclass(frozen=True, slots=True)
class RiskAssessmentReport:
    repository_id: str
    commit_sha: str | None
    assessed_files: list[RiskItem] = field(default_factory=list)
    high_risk_files: list[RiskItem] = field(default_factory=list)
    overall_risk_score: float = 0.0


def _is_covered(source_path: str, test_stems: set[str]) -> bool:
    stem = Path(source_path).stem.lower()
    return any(stem in test_stem for test_stem in test_stems)


def _risk_level(change_count: int, covered: bool) -> str:
    high_churn = change_count >= _HIGH_CHURN_THRESHOLD
    if high_churn and not covered:
        return "high"
    if high_churn or not covered:
        return "medium"
    return "low"


def analyze(context: RepositoryContext) -> RiskAssessmentReport:
    if context.evolution_signals is None:
        return RiskAssessmentReport(repository_id=context.repository_id, commit_sha=context.commit_sha)

    source_paths = {entry.relative_path for entry in context.file_tree if entry.category == "source"}
    test_stems = {Path(entry.relative_path).stem.lower() for entry in context.file_tree if entry.category == "test"}

    items: list[RiskItem] = []
    for stat in context.evolution_signals.file_churn:
        if stat.path not in source_paths:
            continue
        covered = _is_covered(stat.path, test_stems)
        items.append(
            RiskItem(
                path=stat.path,
                change_count=stat.change_count,
                has_associated_test=covered,
                risk_level=_risk_level(stat.change_count, covered),
            )
        )

    items.sort(key=lambda item: (-item.change_count, item.path))
    high_risk = [item for item in items if item.risk_level == "high"]

    total_churn = sum(item.change_count for item in items)
    high_risk_churn = sum(item.change_count for item in high_risk)
    overall_score = round(high_risk_churn / total_churn, 4) if total_churn else 0.0

    return RiskAssessmentReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        assessed_files=items,
        high_risk_files=high_risk,
        overall_risk_score=overall_score,
    )
