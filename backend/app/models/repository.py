"""
Repository ORM model.

`id` is the domain repository_id string itself (the provider's real,
immutable repo identifier -- e.g. GitHub's numeric id cast to str, see
app/services/github_provider.py::_to_repository_metadata) rather than a
separate surrogate key, so there is exactly one identity for a repository
across the domain, database, and (future) API layers. This is also the
same value app/services/clone_service.py::workspace_dir_for() uses for
the on-disk workspace directory.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("provider", "owner", "name", name="uq_repository_provider_owner_name"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(index=True)
    source_url: Mapped[str]
    owner: Mapped[str] = mapped_column(index=True)
    name: Mapped[str]
    default_branch: Mapped[str | None] = mapped_column(default=None)
    description: Mapped[str | None] = mapped_column(default=None)
    visibility: Mapped[str] = mapped_column(default="public")
    primary_language: Mapped[str | None] = mapped_column(default=None)
    license_name: Mapped[str | None] = mapped_column(default=None)
    stargazers_count: Mapped[int] = mapped_column(default=0)
    forks_count: Mapped[int] = mapped_column(default=0)
    open_issues_count: Mapped[int] = mapped_column(default=0)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
