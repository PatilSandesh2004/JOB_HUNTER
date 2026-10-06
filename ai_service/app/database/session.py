"""Async SQLAlchemy engine, session factory and FastAPI dependency."""

from collections.abc import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ai_service.app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from ai_service.app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# Columns added after the first release, with the value existing rows get.
_COLUMN_BACKFILL = {
    ("jobs", "verified"): "0",
    ("applications", "mode"): "'review'",
}


def _add_missing_columns(sync_conn) -> None:
    """Additive migration: create_all() never alters existing tables, so add new columns here."""
    inspector = inspect(sync_conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            column_type = column.type.compile(dialect=sync_conn.dialect)
            default = _COLUMN_BACKFILL.get((table.name, column.name))
            ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {column_type}'
            sync_conn.execute(text(ddl + (f" DEFAULT {default}" if default else "")))

    for (table_name, column_name), carry_over in _OBSOLETE_COLUMNS.items():
        if inspector.has_table(table_name) and column_name in {c["name"] for c in inspector.get_columns(table_name)}:
            if carry_over:
                sync_conn.execute(text(carry_over))
            sync_conn.execute(text(f'ALTER TABLE {table_name} DROP COLUMN "{column_name}"'))


# Columns removed from the models (NOT NULL leftovers would break inserts), with data to carry over first.
_OBSOLETE_COLUMNS = {
    ("applications", "auto_submit"): "UPDATE applications SET mode = 'auto' WHERE auto_submit",
}


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
