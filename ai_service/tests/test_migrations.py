"""Alembic migrations: fresh databases match the models, pre-Alembic databases are adopted intact."""

import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from ai_service.app import models  # noqa: F401
from ai_service.app.database.session import Base, _migrate, alembic_config

HEAD = ScriptDirectory.from_config(alembic_config()).get_current_head()

# Schema written by create_all() before migrations existed (an older release: no jobs.verified, no
# applications.mode, and the since-removed applications.auto_submit).
LEGACY_SCHEMA = """
CREATE TABLE candidates (id VARCHAR(36) NOT NULL PRIMARY KEY, name VARCHAR(200) NOT NULL, email VARCHAR(320),
    phone VARCHAR(64), location VARCHAR(200), current_role VARCHAR(200), current_company VARCHAR(200),
    years_of_experience FLOAT NOT NULL, summary TEXT, linkedin_url VARCHAR(500), github_url VARCHAR(500),
    portfolio_url VARCHAR(500), skills JSON NOT NULL, work_experience JSON NOT NULL, education JSON NOT NULL,
    preferences JSON NOT NULL, resume_path VARCHAR(1000), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE INDEX ix_candidates_email ON candidates (email);
CREATE TABLE jobs (id VARCHAR(36) NOT NULL PRIMARY KEY, title VARCHAR(300) NOT NULL, company VARCHAR(200) NOT NULL,
    description TEXT NOT NULL, location VARCHAR(200) NOT NULL, workplace_type VARCHAR(32) NOT NULL,
    remote_scope VARCHAR(48) NOT NULL, employment_type VARCHAR(64), salary_min FLOAT, salary_max FLOAT,
    salary_currency VARCHAR(8), experience_required FLOAT, required_skills JSON NOT NULL,
    visa_sponsorship JSON NOT NULL, relocation BOOLEAN NOT NULL, application_url VARCHAR(1000) NOT NULL,
    ats VARCHAR(32) NOT NULL, source VARCHAR(64) NOT NULL, posted_at DATETIME, "match" JSON,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE INDEX ix_jobs_title ON jobs (title);
CREATE UNIQUE INDEX ix_jobs_application_url ON jobs (application_url);
CREATE INDEX ix_jobs_company ON jobs (company);
CREATE TABLE applications (id VARCHAR(36) NOT NULL PRIMARY KEY,
    candidate_id VARCHAR(36) NOT NULL REFERENCES candidates (id),
    job_id VARCHAR(36) NOT NULL REFERENCES jobs (id), job_title VARCHAR(300) NOT NULL, company VARCHAR(200) NOT NULL,
    application_url VARCHAR(1000) NOT NULL, status VARCHAR(32) NOT NULL, auto_submit BOOLEAN NOT NULL,
    cover_letter TEXT, cover_letter_source VARCHAR(16), filled_fields JSON NOT NULL, missing_fields JSON NOT NULL,
    screenshot_path VARCHAR(1000), confirmation TEXT, error TEXT, applied_at DATETIME,
    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
CREATE INDEX ix_applications_status ON applications (status);
INSERT INTO candidates VALUES ('c1', 'Asha Rao', 'asha@example.com', NULL, NULL, NULL, NULL, 4, NULL, NULL, NULL,
    NULL, '[]', '[]', '[]', '{}', NULL, '2026-01-01', '2026-01-01');
INSERT INTO jobs VALUES ('j1', 'AI Engineer', 'Acme', '', 'Remote', 'REMOTE', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL,
    '[]', '{}', 0, 'https://jobs.lever.co/acme/1', 'lever', 'searxng', NULL, '{"overall_match": 81.5}',
    '2026-01-01', '2026-01-01');
INSERT INTO jobs VALUES ('j2', 'Data Engineer', 'Beta', '', 'Remote', 'REMOTE', 'UNKNOWN', NULL, NULL, NULL, NULL, NULL,
    '[]', '{}', 0, 'https://jobs.lever.co/beta/2', 'lever', 'searxng', NULL, NULL, '2026-01-01', '2026-01-01');
INSERT INTO applications VALUES ('a1', 'c1', 'j1', 'AI Engineer', 'Acme', 'https://jobs.lever.co/acme/1',
    'NEEDS_MANUAL', 1, NULL, NULL, '{}', '[]', NULL, NULL, NULL, NULL, '2026-01-01', '2026-01-01');
INSERT INTO applications VALUES ('a2', 'c1', 'j2', 'Data Engineer', 'Beta', 'https://jobs.lever.co/beta/2',
    'PENDING_APPROVAL', 0, NULL, NULL, '{}', '[]', NULL, NULL, NULL, NULL, '2026-01-01', '2026-01-01');
"""


async def _migrate_file(path) -> list:
    """Run the app's startup migration against a database file; return the schema diff vs the models."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_migrate)
        async with engine.connect() as conn:
            return await conn.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata))
    finally:
        await engine.dispose()


async def test_fresh_database_matches_models(tmp_path):
    db = tmp_path / "fresh.db"
    assert await _migrate_file(db) == []
    assert await _migrate_file(db) == []  # restart: nothing left to do
    assert sqlite3.connect(db).execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)


async def test_legacy_database_is_adopted_without_data_loss(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(LEGACY_SCHEMA)

    await _migrate_file(db)

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (HEAD,)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(applications)")}
    assert "mode" in columns and "auto_submit" not in columns
    assert dict(conn.execute("SELECT id, mode FROM applications")) == {"a1": "auto", "a2": "review"}
    assert dict(conn.execute("SELECT id, overall_match FROM jobs")) == {"j1": 81.5, "j2": None}
    assert conn.execute("SELECT name FROM candidates").fetchone() == ("Asha Rao",)


@pytest.mark.parametrize("target", ["0001", "base"])
async def test_downgrade_then_upgrade(tmp_path, target):
    db = tmp_path / "roundtrip.db"
    await _migrate_file(db)
    engine = create_async_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: command.downgrade(alembic_config(c), target))
    finally:
        await engine.dispose()
    assert await _migrate_file(db) == []
