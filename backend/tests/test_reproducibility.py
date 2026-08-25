"""
Phase 16: reproducibility.

The plan's requirement: "re-running the same URL/branch either reuses
valid cached analysis for that exact commit SHA or produces a fresh,
consistent run." This system takes the second, simpler option -- there
is no analysis cache (every ingestion/refresh runs the full pipeline
again, see app/services/ingestion_orchestrator.py) -- so what needs
proving is that a repeat run against unchanged upstream data is
genuinely *consistent*: the same commit SHA, and the same substantive
facts (languages, test frameworks, dependencies, file inventory, commit
count), not something that drifts between runs due to e.g. unstable
iteration order.
"""

from __future__ import annotations

import respx

from tests.test_api_repositories import OWNER, REPO, mock_github, patch_clone


def test_reingesting_unchanged_repository_produces_consistent_facts(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)

    with respx.mock:
        mock_github(respx)
        first = api_client.post(
            "/api/v1/repositories/github", json={"repository_url": f"https://github.com/{OWNER}/{REPO}"}
        ).json()

    with respx.mock:
        mock_github(respx)
        second = api_client.post(
            f"/api/v1/repositories/{first['repository_id']}/refresh", json={}
        ).json()

    # Same Repository row reused, not duplicated. The enqueue response
    # itself is captured before the background job resolves anything
    # (status "QUEUED", branch/commit still null -- see Phase 11), so
    # fetch each run's live status for the resolved facts.
    assert second["repository_id"] == first["repository_id"]
    first_run = api_client.get(
        f"/api/v1/repositories/{first['repository_id']}/analysis-runs/{first['analysis_run_id']}"
    ).json()
    second_run = api_client.get(
        f"/api/v1/repositories/{second['repository_id']}/analysis-runs/{second['analysis_run_id']}"
    ).json()
    assert second_run["branch_name"] == first_run["branch_name"] == "main"
    assert second_run["commit_sha"] == first_run["commit_sha"] == "sha-main"
    assert second_run["status"] == first_run["status"] == "READY"

    profile1 = api_client.get(f"/api/v1/repositories/{first['repository_id']}/profile").json()["profile"]
    profile2 = api_client.get(f"/api/v1/repositories/{second['repository_id']}/profile").json()["profile"]

    # Substantive facts match exactly between the two runs; only
    # bookkeeping fields (updated_at) are expected to differ.
    for field in ("languages", "test_frameworks", "test_directories", "dependencies", "file_inventory"):
        assert profile1[field] == profile2[field], f"{field} drifted between two runs of the same commit"
    assert profile1["git_history_summary"]["commit_count"] == profile2["git_history_summary"]["commit_count"]
    assert profile1["commit_sha"] == profile2["commit_sha"]


def test_reingesting_same_repository_reuses_one_repository_row_across_many_runs(api_client, monkeypatch, tmp_path):
    patch_clone(monkeypatch, tmp_path)
    repository_id = None

    for _ in range(3):
        with respx.mock:
            mock_github(respx)
            if repository_id is None:
                body = api_client.post(
                    "/api/v1/repositories/github", json={"repository_url": f"https://github.com/{OWNER}/{REPO}"}
                ).json()
            else:
                body = api_client.post(f"/api/v1/repositories/{repository_id}/refresh", json={}).json()
        repository_id = body["repository_id"]

    listing = api_client.get("/api/v1/repositories").json()
    assert listing["total"] == 1  # three ingestions of the same repo, one row
