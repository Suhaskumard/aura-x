"""
AnalysisRun ORM model (Phase 9): one row per ingestion attempt. Carries
the persisted ingestion state machine (mirrors app.domain.repository_
context.IngestionStatus/ALLOWED_TRANSITIONS -- see
app/db/repository_dao.py::transition_analysis_run, which enforces the
same allow-list against this row) and, for reproducibility, exactly which
repository/branch/commit/configuration were analyzed.

`status` is stored as the plain string value of IngestionStatus rather
than a native DB enum type, so the same model works unchanged against
SQLite (used in tests, and optionally local dev) and Postgres (production)
without a database-specific migration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.repository_context import IngestionStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Exactly what was analyzed -- see "Guarantee reproducibility" in
    # docs/GITHUB_INTEGRATION.md.
    branch_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=IngestionStatus.PENDING.value, index=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The Repository Profile view (app/services/repository_service.py::
    # build_repository_profile) as of this run -- languages, test
    # frameworks, dependencies, file inventory, git history summary. Set
    # once the run reaches READY.
    result_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    repository: Mapped["Repository"] = relationship(back_populates="analysis_runs")
