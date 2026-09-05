"""
Verifies the Phase 9 Alembic migration actually applies to and reverses
against a real SQLite database, matching the ORM models exactly -- not
just that `Base.metadata.create_all()` works (that's covered by
test_db_models.py), but that the checked-in migration script itself is
correct end to end.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch) -> Config:
    from app.core.config import get_settings

    db_path = tmp_path / "alembic_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # get_settings() is lru_cache'd -- an earlier test in this process may
    # have already cached a Settings instance built from a different
    # DATABASE_URL, which the env var change above wouldn't otherwise
    # affect. alembic/env.py calls get_settings() at import time, so the
    # cache must be cleared for it to see this test's URL.
    get_settings.cache_clear()

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.attributes["configure_logger"] = False
    yield config, db_path
    get_settings.cache_clear()


def test_upgrade_head_creates_expected_tables(alembic_config):
    config, db_path = alembic_config
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert {"repositories", "branches", "analysis_runs", "alembic_version"} <= table_names

    branch_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("branches")}
    assert branch_fks == {"repositories"}

    run_fks = {fk["referred_table"] for fk in inspector.get_foreign_keys("analysis_runs")}
    assert run_fks == {"repositories", "branches"}


def test_downgrade_base_removes_all_tables(alembic_config):
    config, db_path = alembic_config
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names()) - {"alembic_version"}
    assert table_names == set()


def test_migration_schema_matches_orm_metadata_create_all(alembic_config, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.db.base import Base
    import app.models  # noqa: F401

    config, db_path = alembic_config
    command.upgrade(config, "head")
    migrated_engine = create_engine(f"sqlite:///{db_path}")
    migrated_tables = set(inspect(migrated_engine).get_table_names()) - {"alembic_version"}

    direct_db_path = tmp_path / "direct_create_all.db"
    direct_engine = create_engine(f"sqlite:///{direct_db_path}")
    Base.metadata.create_all(direct_engine)
    direct_tables = set(inspect(direct_engine).get_table_names())

    assert migrated_tables == direct_tables
