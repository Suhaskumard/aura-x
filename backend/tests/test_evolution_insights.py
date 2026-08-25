from datetime import datetime, timezone

from app.analysis.evolution_insights import analyze
from app.domain.evolution import CoChangePair, EvolutionSignals, FileChurnStat
from app.domain.repository_context import RepositoryContext


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


def test_analyze_with_no_evolution_signals_returns_unknown_pattern():
    context = make_context(evolution_signals=None)
    report = analyze(context)

    assert report.churn_pattern == "unknown"
    assert report.hotspot_files == []
    assert report.tightly_coupled_pairs == []


def test_analyze_with_no_churn_returns_none_pattern():
    context = make_context(
        evolution_signals=EvolutionSignals(analyzed_commit_count=3, file_churn=[], co_changes=[], change_concentration=0.0)
    )
    report = analyze(context)
    assert report.churn_pattern == "none"


def test_analyze_reports_hotspots_from_signals():
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    signals = EvolutionSignals(
        analyzed_commit_count=5,
        file_churn=[
            FileChurnStat(path="app/hot.py", change_count=5, additions=10, deletions=2, last_changed_at=ts),
            FileChurnStat(path="app/cold.py", change_count=1, additions=1, deletions=0, last_changed_at=ts),
        ],
        co_changes=[],
        change_concentration=0.8,
    )
    context = make_context(evolution_signals=signals)
    report = analyze(context)

    assert report.analyzed_commit_count == 5
    assert [h.path for h in report.hotspot_files] == ["app/hot.py", "app/cold.py"]
    assert report.hotspot_files[0].change_count == 5
    assert report.hotspot_files[0].last_changed_at == ts
    assert report.churn_pattern == "concentrated"


def test_analyze_reports_coupling_pairs():
    signals = EvolutionSignals(
        analyzed_commit_count=2,
        file_churn=[FileChurnStat(path="a.py", change_count=2, additions=0, deletions=0)],
        co_changes=[CoChangePair(file_a="a.py", file_b="b.py", co_change_count=2)],
        change_concentration=0.3,
    )
    context = make_context(evolution_signals=signals)
    report = analyze(context)

    assert len(report.tightly_coupled_pairs) == 1
    assert report.tightly_coupled_pairs[0].file_a == "a.py"
    assert report.tightly_coupled_pairs[0].co_change_count == 2
    assert report.churn_pattern == "distributed"


def test_analyze_limits_hotspots_and_pairs_to_top_ten():
    file_churn = [FileChurnStat(path=f"f{i}.py", change_count=20 - i, additions=0, deletions=0) for i in range(15)]
    co_changes = [CoChangePair(file_a=f"a{i}.py", file_b=f"b{i}.py", co_change_count=20 - i) for i in range(15)]
    signals = EvolutionSignals(analyzed_commit_count=20, file_churn=file_churn, co_changes=co_changes, change_concentration=0.5)
    context = make_context(evolution_signals=signals)
    report = analyze(context)

    assert len(report.hotspot_files) == 10
    assert len(report.tightly_coupled_pairs) == 10


def test_analyze_carries_repository_id_and_commit_sha():
    context = make_context(repository_id="repo-xyz", commit_sha="deadbeef", evolution_signals=None)
    report = analyze(context)
    assert report.repository_id == "repo-xyz"
    assert report.commit_sha == "deadbeef"
