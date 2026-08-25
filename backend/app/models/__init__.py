"""
SQLAlchemy ORM models (Phase 9: Database Persistence).

Importing this package registers every model class against
app.db.base.Base's declarative registry, which is required before:
  - Base.metadata.create_all()/drop_all() (tests, local SQLite dev), or
  - Alembic autogenerate/migration (migrations/env.py imports this module)
can see the full schema, and before any relationship() with a string
forward reference (e.g. Mapped["Branch"]) can be resolved.
"""

from app.models.analysis_run import AnalysisRun
from app.models.branch import Branch
from app.models.commit import Commit
from app.models.repository import Repository

__all__ = ["Repository", "Branch", "Commit", "AnalysisRun"]
