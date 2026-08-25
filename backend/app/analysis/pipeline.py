"""
Downstream analysis pipeline (Phase 12): runs Repository Intelligence,
Evolution Analysis, Dependency Analysis, Risk Assessment, and Test
Planning against a single, completed RepositoryContext, and bundles their
reports together.

Every report carries the same repository_id/commit_sha copied straight
from `context` -- by construction, not by cross-checking after the fact
-- so a single ingestion run's repository/branch/commit selection is
guaranteed consistent across every stage. See
tests/test_analysis_pipeline.py for the integration test verifying this
end-to-end with a real assembled context.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis import dependency_analysis, evolution_insights, planning, repository_intelligence, risk_assessment
from app.domain.repository_context import IngestionStatus, RepositoryContext


@dataclass(frozen=True, slots=True)
class DownstreamAnalysisResult:
    repository_id: str
    commit_sha: str | None
    intelligence: repository_intelligence.RepositoryIntelligenceReport
    evolution: evolution_insights.EvolutionInsightsReport
    dependencies: dependency_analysis.DependencyAnalysisReport
    risk: risk_assessment.RiskAssessmentReport
    test_planning: planning.TestPlanningReport


def run_downstream_analysis(context: RepositoryContext) -> DownstreamAnalysisResult:
    """Run all five downstream stages against `context`. Requires a READY
    context -- "the completed RepositoryContext" per this phase's own
    framing -- since a context that never finished ingestion (no
    file_tree/evolution_signals/local_path) would produce misleadingly
    empty reports rather than a real analysis.
    """
    if context.analysis_status != IngestionStatus.READY:
        raise ValueError(
            f"Downstream analysis requires a READY RepositoryContext, got {context.analysis_status.value}"
        )

    intelligence = repository_intelligence.analyze(context)
    evolution = evolution_insights.analyze(context)
    dependencies = dependency_analysis.analyze(context)
    risk = risk_assessment.analyze(context)
    test_planning_report = planning.analyze(context, risk_report=risk)

    return DownstreamAnalysisResult(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        intelligence=intelligence,
        evolution=evolution,
        dependencies=dependencies,
        risk=risk,
        test_planning=test_planning_report,
    )
