from datetime import datetime, timedelta, timezone

from app.domain.models import CommitInfo, FileChange
from app.services.evolution_analysis import compute_evolution_signals

BASE_TIME = datetime(2024, 1, 10, tzinfo=timezone.utc)


def commit(sha: str, files: list[FileChange], *, days_ago: int = 0) -> CommitInfo:
    return CommitInfo(
        sha=sha,
        parents=[],
        author_name="Ada Lovelace",
        author_email="ada@example.com",
        committed_at=BASE_TIME - timedelta(days=days_ago),
        message=f"commit {sha}",
        changed_files=files,
    )


def fc(path: str, additions: int = 1, deletions: int = 0) -> FileChange:
    return FileChange(path=path, additions=additions, deletions=deletions)


def test_empty_history_returns_empty_signals():
    signals = compute_evolution_signals([])
    assert signals.analyzed_commit_count == 0
    assert signals.file_churn == []
    assert signals.recently_changed_files == []
    assert signals.co_changes == []
    assert signals.change_concentration == 0.0


def test_commits_without_changed_files_are_counted_but_contribute_no_churn():
    commits = [commit("a", []), commit("b", [])]
    signals = compute_evolution_signals(commits)
    assert signals.analyzed_commit_count == 2
    assert signals.file_churn == []


def test_file_churn_counts_and_sums_additions_deletions():
    commits = [
        commit("a", [fc("app/main.py", additions=10, deletions=2)], days_ago=2),
        commit("b", [fc("app/main.py", additions=5, deletions=1)], days_ago=1),
        commit("c", [fc("app/other.py", additions=3)], days_ago=0),
    ]
    signals = compute_evolution_signals(commits)
    by_path = {stat.path: stat for stat in signals.file_churn}

    assert by_path["app/main.py"].change_count == 2
    assert by_path["app/main.py"].additions == 15
    assert by_path["app/main.py"].deletions == 3
    assert by_path["app/other.py"].change_count == 1
    # most churned file first
    assert signals.file_churn[0].path == "app/main.py"


def test_last_changed_at_tracks_most_recent_commit_touching_file():
    commits = [
        commit("older", [fc("app/main.py")], days_ago=5),
        commit("newer", [fc("app/main.py")], days_ago=0),
    ]
    signals = compute_evolution_signals(commits)
    stat = signals.file_churn[0]
    assert stat.last_changed_at == BASE_TIME


def test_recently_changed_files_preserves_newest_first_order_deduped():
    commits = [
        commit("newest", [fc("a.py"), fc("b.py")], days_ago=0),
        commit("older", [fc("b.py"), fc("c.py")], days_ago=1),
    ]
    signals = compute_evolution_signals(commits)
    assert signals.recently_changed_files == ["a.py", "b.py", "c.py"]


def test_recently_changed_files_respects_limit():
    commits = [commit(f"c{i}", [fc(f"file{i}.py")]) for i in range(5)]
    signals = compute_evolution_signals(commits, recent_file_limit=2)
    assert len(signals.recently_changed_files) == 2


def test_co_changes_detects_files_that_change_together():
    commits = [
        commit("a", [fc("x.py"), fc("y.py")]),
        commit("b", [fc("x.py"), fc("y.py")]),
        commit("c", [fc("x.py")]),
    ]
    signals = compute_evolution_signals(commits)
    assert len(signals.co_changes) == 1
    pair = signals.co_changes[0]
    assert {pair.file_a, pair.file_b} == {"x.py", "y.py"}
    assert pair.co_change_count == 2


def test_co_changes_excludes_pairs_that_only_co_occur_once():
    commits = [commit("a", [fc("x.py"), fc("y.py")])]
    signals = compute_evolution_signals(commits)
    assert signals.co_changes == []


def test_co_changes_respects_top_n():
    files = [f"file{i}.py" for i in range(6)]
    commits = [commit("a", [fc(f) for f in files]), commit("b", [fc(f) for f in files])]
    signals = compute_evolution_signals(commits, co_change_top_n=3)
    assert len(signals.co_changes) == 3


def test_change_concentration_is_between_zero_and_one():
    commits = [
        commit("a", [fc("hot.py")]),
        commit("b", [fc("hot.py")]),
        commit("c", [fc("hot.py")]),
        commit("d", [fc("cold.py")]),
    ]
    signals = compute_evolution_signals(commits)
    assert 0.0 < signals.change_concentration <= 1.0


# ---- Regression: a mass-change commit must not blow up co-change computation ----
# combinations(paths, 2) is O(n^2) in a single commit's touched-file count.
# An initial-import or vendor-update commit touching thousands of files
# used to generate millions of pairs (~79s / a huge dict for 3000 files,
# measured before the fix) -- file_churn/recently_changed stay accurate
# for such a commit; only its (not meaningful) co-change pairing is
# skipped once it exceeds max_co_change_files_per_commit.


def test_mass_change_commit_skips_co_change_pairing_but_keeps_churn():
    huge_commit = commit("huge", [fc(f"file{i}.py") for i in range(500)])
    signals = compute_evolution_signals([huge_commit], max_co_change_files_per_commit=100)
    assert signals.co_changes == []  # pairing skipped -- commit exceeds the cap
    assert len(signals.file_churn) == 500  # churn/count stats still computed per file
    assert signals.recently_changed_files  # recently-changed tracking unaffected


def test_mass_change_commit_does_not_suppress_co_changes_from_other_commits():
    huge_commit = commit("huge", [fc(f"file{i}.py") for i in range(500)])
    small_commit_a = commit("a", [fc("x.py"), fc("y.py")], days_ago=1)
    small_commit_b = commit("b", [fc("x.py"), fc("y.py")], days_ago=2)
    signals = compute_evolution_signals(
        [huge_commit, small_commit_a, small_commit_b], max_co_change_files_per_commit=100
    )
    assert any(pair.file_a == "x.py" and pair.file_b == "y.py" for pair in signals.co_changes)


def test_compute_evolution_signals_stays_fast_for_a_large_single_commit():
    import time

    huge_commit = commit("huge", [fc(f"file{i}.py") for i in range(3000)])
    started = time.perf_counter()
    compute_evolution_signals([huge_commit])
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0  # was ~79s before the O(n^2) co-change cap
