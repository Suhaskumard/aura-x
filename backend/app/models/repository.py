"""
Repository ORM model (Phase 9). One row per (provider, owner, name) --
re-ingesting the same repository updates this row and adds a new
AnalysisRun, rather than creating a duplicate Repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("provider", "owner", "name", name="uq_repositories_provider_owner_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_repository_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    default_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String(16), nullable=True)
    primary_language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    stargazers_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    forks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_issues_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Timestamps as reported by the provider (e.g. GitHub's repo created_at/
    # updated_at) -- distinct from created_at/updated_at below, which track
    # this row's own local bookkeeping.
    remote_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    branches: Mapped[list["Branch"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    commits: Mapped[list["Commit"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
