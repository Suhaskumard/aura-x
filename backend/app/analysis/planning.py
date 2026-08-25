"""
Test Planning (Phase 12): turns Risk Assessment's high-risk files into
concrete, prioritized test-writing recommendations, using the test
frameworks Phase 8 already detected (so a recommendation can say "add a
pytest test for ...", not just "add a test for ...").

`risk_report` is optional -- when omitted, this module computes it itself
via app.analysis.risk_assessment.analyze(context) so that
RepositoryContext alone is still sufficient to call this entry point
(per this phase's "sole repository input" requirement); the pipeline
orchestrator (app/analysis/pipeline.py) passes an already-computed one to
avoid running that analysis twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.risk_assessment import RiskAssessmentReport, analyze as analyze_risk
from app.domain.repository_context import RepositoryContext


@dataclass(frozen=True, slots=True)
class TestRecommendation:
    path: str
    reason: str
    priority: str  # "high" | "medium"


@dataclass(frozen=True, slots=True)
class TestPlanningReport:
    repository_id: str
    commit_sha: str | None
    detected_frameworks: list[str] = field(default_factory=list)
    recommendations: list[TestRecommendation] = field(default_factory=list)


def _reason(item, frameworks: list[str]) -> str:
    framework_hint = f" (using {frameworks[0]})" if frameworks else ""
    return f"Changed {item.change_count} time(s) with no detected test coverage{framework_hint}"


def analyze(context: RepositoryContext, risk_report: RiskAssessmentReport | None = None) -> TestPlanningReport:
    if risk_report is None:
        risk_report = analyze_risk(context)

    frameworks = list(context.test_frameworks)
    recommendations = [
        TestRecommendation(path=item.path, reason=_reason(item, frameworks), priority="high")
        for item in risk_report.high_risk_files
    ]

    return TestPlanningReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        detected_frameworks=frameworks,
        recommendations=recommendations,
    )
