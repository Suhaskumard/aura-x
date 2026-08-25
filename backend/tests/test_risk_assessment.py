from app.analysis.risk_assessment import analyze
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


def churn(path: str, count: int) -> FileChurnStat:
    return FileChurnStat(path=path, change_count=count, additions=0, deletions=0)


def test_analyze_without_evolution_signals_returns_empty_report():
    context = make_context(evolution_signals=None)
    report = analyze(context)
    assert report.assessed_files == []
    assert report.high_risk_files == []
    assert report.overall_risk_score == 0.0


def test_high_churn_untested_file_is_high_risk():
    context = make_context(
        file_tree=[entry("app/risky.py", "source")],
        evolution_signals=EvolutionSignals(analyzed_commit_count=5, file_churn=[churn("app/risky.py", 5)], co_changes=[], change_concentration=1.0),
    )
    report = analyze(context)

    assert len(report.high_risk_files) == 1
    item = report.high_risk_files[0]
    assert item.path == "app/risky.py"
    assert item.has_associated_test is False
    assert item.risk_level == "high"
    assert report.overall_risk_score == 1.0


def test_high_churn_file_with_test_is_medium_not_high():
    context = make_context(
        file_tree=[entry("app/covered.py", "source"), entry("tests/test_covered.py", "test")],
        evolution_signals=EvolutionSignals(analyzed_commit_count=5, file_churn=[churn("app/covered.py", 10)], co_changes=[], change_concentration=1.0),
    )
    report = analyze(context)

    assert report.high_risk_files == []
    assert len(report.assessed_files) == 1
    assert report.assessed_files[0].risk_level == "medium"
    assert report.assessed_files[0].has_associated_test is True


def test_low_churn_untested_file_is_medium():
    context = make_context(
        file_tree=[entry("app/quiet.py", "source")],
        evolution_signals=EvolutionSignals(analyzed_commit_count=1, file_churn=[churn("app/quiet.py", 1)], co_changes=[], change_concentration=1.0),
    )
    report = analyze(context)
    assert report.assessed_files[0].risk_level == "medium"


def test_low_churn_tested_file_is_low_risk():
    context = make_context(
        file_tree=[entry("app/safe.py", "source"), entry("tests/test_safe.py", "test")],
        evolution_signals=EvolutionSignals(analyzed_commit_count=1, file_churn=[churn("app/safe.py", 1)], co_changes=[], change_concentration=1.0),
    )
    report = analyze(context)
    assert report.assessed_files[0].risk_level == "low"


def test_non_source_files_are_excluded_even_if_churned():
    context = make_context(
        file_tree=[entry("README.md", "docs")],
        evolution_signals=EvolutionSignals(analyzed_commit_count=5, file_churn=[churn("README.md", 10)], co_changes=[], change_concentration=1.0),
    )
    report = analyze(context)
    assert report.assessed_files == []


def test_overall_risk_score_weighted_by_churn():
    context = make_context(
        file_tree=[entry("app/hot.py", "source"), entry("app/warm.py", "source"), entry("tests/test_warm.py", "test")],
        evolution_signals=EvolutionSignals(
            analyzed_commit_count=10,
            file_churn=[churn("app/hot.py", 6), churn("app/warm.py", 4)],
            co_changes=[],
            change_concentration=1.0,
        ),
    )
    report = analyze(context)
    # hot.py: high risk (6 churn, untested); warm.py: medium (tested, high churn)
    assert report.overall_risk_score == 0.6  # 6 / (6+4)


def test_analyze_carries_repository_id_and_commit_sha():
    context = make_context(repository_id="repo-xyz", commit_sha="deadbeef", evolution_signals=None)
    report = analyze(context)
    assert report.repository_id == "repo-xyz"
    assert report.commit_sha == "deadbeef"
