"""Async SQLAlchemy engine, session factory, schema migrations and FastAPI dependency."""

from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ai_service.app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)

if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record) -> None:
        # SQLite ignores foreign keys unless asked, which hides bugs PostgreSQL would reject.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
BASELINE_REVISION = "0001"


def alembic_config(connection=None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    return config


async def init_db() -> None:
    """Bring the database schema to the latest Alembic revision."""
    async with engine.begin() as conn:
        await conn.run_sync(_migrate)


def _migrate(sync_conn) -> None:
    config = alembic_config(sync_conn)
    inspector = inspect(sync_conn)
    if inspector.has_table("jobs") and not inspector.has_table("alembic_version"):
        # Created by create_all() before migrations existed: patch it to the baseline, then adopt it.
        _upgrade_legacy_schema(sync_conn)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")


# Pre-Alembic schema changes, applied only to databases that predate the baseline revision.
_LEGACY_ADDED_COLUMNS = {
    ("jobs", "verified"): "BOOLEAN NOT NULL DEFAULT 0",
    ("applications", "mode"): "VARCHAR(16) NOT NULL DEFAULT 'review'",
}
# Columns removed from the models (NOT NULL leftovers would break inserts), with data to carry over first.
_LEGACY_DROPPED_COLUMNS = {
    ("applications", "auto_submit"): "UPDATE applications SET mode = 'auto' WHERE auto_submit",
}


def _upgrade_legacy_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)

    def columns(table: str) -> set[str]:
        return {c["name"] for c in inspector.get_columns(table)} if inspector.has_table(table) else set()

    for (table, column), ddl in _LEGACY_ADDED_COLUMNS.items():
        if inspector.has_table(table) and column not in columns(table):
            sync_conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{column}" {ddl}'))
    for (table, column), carry_over in _LEGACY_DROPPED_COLUMNS.items():
        if column in columns(table):
            sync_conn.execute(text(carry_over))
            sync_conn.execute(text(f'ALTER TABLE {table} DROP COLUMN "{column}"'))


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
