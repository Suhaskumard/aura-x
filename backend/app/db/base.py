"""Declarative base for all ORM models. Phase 9 adds Repository/Branch/
AnalysisRun models here; this module only establishes the shared Base."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
