"""
Public-facing ingestion status vocabulary (Phase 11).

app.domain.repository_context.IngestionStatus (PENDING, VALIDATING,
FETCHING_METADATA, FETCHING_BRANCHES, CLONING, SCANNING, READY, FAILED)
is the persisted, internal state machine -- unchanged since Phase 3/9,
still what AnalysisRun.status stores. The API surface exposes the
coarser vocabulary from the Phase 11 plan (QUEUED, VALIDATING, FETCHING,
CLONING, ANALYZING, READY, FAILED) instead: FETCHING_METADATA and
FETCHING_BRANCHES both read as "FETCHING" (both are "talking to GitHub's
API"), SCANNING reads as "ANALYZING" (matches Phase 8's actual work:
scanning the tree, detecting languages/tests, computing evolution
signals -- "scanning" undersells it). This is a presentation-only
mapping -- it never changes what's stored or how transitions are
validated.
"""

from __future__ import annotations

from app.domain.repository_context import IngestionStatus

PUBLIC_STATUS_BY_INTERNAL: dict[str, str] = {
    IngestionStatus.PENDING.value: "QUEUED",
    IngestionStatus.VALIDATING.value: "VALIDATING",
    IngestionStatus.FETCHING_METADATA.value: "FETCHING",
    IngestionStatus.FETCHING_BRANCHES.value: "FETCHING",
    IngestionStatus.CLONING.value: "CLONING",
    IngestionStatus.SCANNING.value: "ANALYZING",
    IngestionStatus.READY.value: "READY",
    IngestionStatus.FAILED.value: "FAILED",
}


def to_public_status(internal_status: str) -> str:
    return PUBLIC_STATUS_BY_INTERNAL.get(internal_status, internal_status)
