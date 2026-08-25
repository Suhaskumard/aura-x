"""Commit reference ORM model (Phase 9). Stores the bounded commit history
already fetched for analysis (see app/domain/repository_context.py's
git_history field) -- not a full mirror of the repository's git log."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (
        UniqueConstraint("repository_id", "sha", name="uq_commits_repository_sha"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    repository_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    parents: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    additions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{"path": str, "additions": int, "deletions": int, "status": str}, ...]
    changed_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    repository: Mapped["Repository"] = relationship(back_populates="commits")
