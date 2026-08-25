from app.analysis.planning import analyze
from app.analysis.risk_assessment import RiskAssessmentReport, RiskItem
from app.domain.evolution import EvolutionSignals, FileChurnStat
from app.domain.models import FileEntry
from app.domain.repository_context import RepositoryContext


def entry(path: str, category: str) -> FileEntry:
    return FileEntry(relative_path=path, extension="", size_bytes=1, category=category)


def make_context(**overrides) -> RepositoryContext:
    defaults = dict(
        repository_id="repo-1",
        provider="github",
        source_url="https://github.com/octocat/hello-world",
        owner="octocat",
        repository_name="hello-world",
        commit_sha="sha1",
    )
    defaults.update(overrides)
    return RepositoryContext(**defaults)


def test_analyze_computes_risk_internally_when_not_provided():
    context = make_context(
        test_frameworks=["pytest"],
        file_tree=[entry("app/risky.py", "source")],
        evolution_signals=EvolutionSignals(
            analyzed_commit_count=5,
            file_churn=[FileChurnStat(path="app/risky.py", change_count=5, additions=0, deletions=0)],
            co_changes=[],
            change_concentration=1.0,
        ),
    )
    report = analyze(context)

    assert report.detected_frameworks == ["pytest"]
    assert len(report.recommendations) == 1
    assert report.recommendations[0].path == "app/risky.py"
    assert report.recommendations[0].priority == "high"
    assert "pytest" in report.recommendations[0].reason


def test_analyze_accepts_precomputed_risk_report_without_recomputing():
    context = make_context(test_frameworks=[])
    risk_report = RiskAssessmentReport(
        repository_id=context.repository_id,
        commit_sha=context.commit_sha,
        high_risk_files=[RiskItem(path="a.py", change_count=9, has_associated_test=False, risk_level="high")],
    )
    report = analyze(context, risk_report=risk_report)

    assert len(report.recommendations) == 1
    assert report.recommendations[0].path == "a.py"


def test_no_high_risk_files_means_no_recommendations():
    context = make_context()
    report = analyze(context)
    assert report.recommendations == []


def test_analyze_carries_repository_id_and_commit_sha():
    context = make_context(repository_id="repo-xyz", commit_sha="deadbeef")
    report = analyze(context)
    assert report.repository_id == "repo-xyz"
    assert report.commit_sha == "deadbeef"
