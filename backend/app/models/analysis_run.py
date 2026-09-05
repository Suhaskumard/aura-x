"""
AnalysisRun ORM model.

`status` mirrors app.domain.repository_context.IngestionStatus (stored as
its .value). `branch_id` is nullable because a run must be persistable
(including a FAILED outcome) before branch resolution completes --
PENDING/VALIDATING/FETCHING_METADATA all precede FETCHING_BRANCHES in the
state machine. `requested_branch` records what the caller asked for as
an audit trail regardless of whether resolution succeeded. `scan_result`
(Phase 12) is the JSON-serialized Phase 8 ScanResult (file_tree,
languages, test_frameworks, evolution_signals) -- see
app/services/context_builder.py for the (de)serialization and the
RepositoryContext this feeds.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (Index("ix_analysis_run_repository_branch", "repository_id", "branch_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[str] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("branches.id", ondelete="SET NULL"), default=None
    )
    requested_branch: Mapped[str | None] = mapped_column(default=None)
    commit_sha: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="PENDING")
    last_error: Mapped[dict | None] = mapped_column(JSON, default=None)
    scan_result: Mapped[dict | None] = mapped_column(JSON, default=None)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
