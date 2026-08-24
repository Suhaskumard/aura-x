"""
RepositoryContext: the single normalized object downstream AURA-X modules
(Repository Intelligence, Evolution Analysis, Risk Engine, Test Planning,
Reporting) depend on. They must never import a provider-specific type.

See docs/GITHUB_INTEGRATION.md "RepositoryContext schema" for the field
table this class implements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.domain.errors import InvalidStateTransitionError
from app.domain.models import BranchInfo, CommitInfo, FileEntry, RepositoryMetadata


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    FETCHING_METADATA = "FETCHING_METADATA"
    FETCHING_BRANCHES = "FETCHING_BRANCHES"
    CLONING = "CLONING"
    SCANNING = "SCANNING"
    READY = "READY"
    FAILED = "FAILED"


# Explicit allow-list of legal transitions. FAILED is reachable from any
# non-terminal state; READY and FAILED are terminal (no outgoing edges).
ALLOWED_TRANSITIONS: dict[IngestionStatus, frozenset[IngestionStatus]] = {
    IngestionStatus.PENDING: frozenset({IngestionStatus.VALIDATING, IngestionStatus.FAILED}),
    IngestionStatus.VALIDATING: frozenset({IngestionStatus.FETCHING_METADATA, IngestionStatus.FAILED}),
    IngestionStatus.FETCHING_METADATA: frozenset({IngestionStatus.FETCHING_BRANCHES, IngestionStatus.FAILED}),
    IngestionStatus.FETCHING_BRANCHES: frozenset({IngestionStatus.CLONING, IngestionStatus.FAILED}),
    IngestionStatus.CLONING: frozenset({IngestionStatus.SCANNING, IngestionStatus.FAILED}),
    IngestionStatus.SCANNING: frozenset({IngestionStatus.READY, IngestionStatus.FAILED}),
    IngestionStatus.READY: frozenset(),
    IngestionStatus.FAILED: frozenset(),
}


@dataclass(slots=True)
class RepositoryContext:
    repository_id: str
    provider: str
    source_url: str
    owner: str
    repository_name: str

    local_path: str | None = None
    selected_branch: str | None = None
    default_branch: str | None = None
    commit_sha: str | None = None

    metadata: RepositoryMetadata | None = None
    branches: list[BranchInfo] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    file_tree: list[FileEntry] = field(default_factory=list)
    git_history: list[CommitInfo] = field(default_factory=list)

    analysis_status: IngestionStatus = IngestionStatus.PENDING
    last_error: dict | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition_to(self, new_status: IngestionStatus) -> None:
        allowed = ALLOWED_TRANSITIONS[self.analysis_status]
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition from {self.analysis_status.value} to {new_status.value}"
            )
        self.analysis_status = new_status
        self.updated_at = datetime.now(timezone.utc)

    def fail(self, error: dict) -> None:
        """Convenience for transitioning to FAILED with a structured error
        payload (never a raw exception or secret value) attached."""
        self.transition_to(IngestionStatus.FAILED)
        self.last_error = error

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["analysis_status"] = self.analysis_status.value
        return payload
