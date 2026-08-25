"""Database engine/session wiring. Uses app.core.config.get_settings() so
the connection string is never hardcoded."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker:
    """Returns the session factory itself (not an opened Session) -- for
    code that needs to open its own session outside the request lifecycle,
    e.g. a FastAPI BackgroundTask (Phase 11), which runs after the request
    that scheduled it has already returned and its `get_db`-injected
    Session has been closed. A FastAPI dependency (rather than importing
    SessionLocal directly) so tests can override it to a per-test engine,
    same as get_db."""
    return SessionLocal
