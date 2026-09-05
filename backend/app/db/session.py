"""Database engine/session wiring. Uses app.core.config.get_settings() so
the connection string is never hardcoded."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _ensure_sqlite_parent_dir_exists(database_url: str) -> None:
    # sqlite3 opens the DB file itself but never creates a missing parent
    # directory -- on a fresh checkout (nothing has run yet, so
    # .workspace/ doesn't exist) that surfaces as an opaque
    # "unable to open database file" OperationalError with no indication
    # it's a missing directory, not a permissions or corruption problem.
    url = make_url(database_url)
    database = url.database
    if not database or database == ":memory:":
        return
    Path(database).parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Build an engine for `settings.database_url`. Tests call this
    directly with a Settings pointed at a real temp-file SQLite DB, so the
    exact same dialect-conditional wiring (connect_args, FK pragma) is
    exercised in tests as in production -- no divergent test-only path."""
    settings = settings or get_settings()
    sqlite = _is_sqlite(settings.database_url)

    if sqlite:
        _ensure_sqlite_parent_dir_exists(settings.database_url)

    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"check_same_thread": False} if sqlite else {},
    )

    if sqlite:
        # SQLite ignores FK constraints (and therefore ondelete=CASCADE/
        # SET NULL) unless explicitly enabled per connection. Without this,
        # cascade behavior would silently no-op while appearing to work.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


settings = get_settings()
engine = create_db_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
