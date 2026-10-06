"""Baseline: candidates, jobs and applications as created by create_all() before Alembic.

Databases created before migrations existed are brought to this schema by
database/session.py:_upgrade_legacy_schema and stamped with this revision.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(64)),
        sa.Column("location", sa.String(200)),
        sa.Column("current_role", sa.String(200)),
        sa.Column("current_company", sa.String(200)),
        sa.Column("years_of_experience", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("linkedin_url", sa.String(500)),
        sa.Column("github_url", sa.String(500)),
        sa.Column("portfolio_url", sa.String(500)),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("work_experience", sa.JSON(), nullable=False),
        sa.Column("education", sa.JSON(), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("resume_path", sa.String(1000)),
        *_timestamps(),
    )
    op.create_index("ix_candidates_email", "candidates", ["email"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(200), nullable=False),
        sa.Column("workplace_type", sa.String(32), nullable=False),
        sa.Column("remote_scope", sa.String(48), nullable=False),
        sa.Column("employment_type", sa.String(64)),
        sa.Column("salary_min", sa.Float()),
        sa.Column("salary_max", sa.Float()),
        sa.Column("salary_currency", sa.String(8)),
        sa.Column("experience_required", sa.Float()),
        sa.Column("required_skills", sa.JSON(), nullable=False),
        sa.Column("visa_sponsorship", sa.JSON(), nullable=False),
        sa.Column("relocation", sa.Boolean(), nullable=False),
        sa.Column("application_url", sa.String(1000), nullable=False),
        sa.Column("ats", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("match", sa.JSON()),
        *_timestamps(),
    )
    op.create_index("ix_jobs_title", "jobs", ["title"])
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_application_url", "jobs", ["application_url"], unique=True)

    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("job_title", sa.String(300), nullable=False),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("application_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("cover_letter", sa.Text()),
        sa.Column("cover_letter_source", sa.String(16)),
        sa.Column("filled_fields", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("screenshot_path", sa.String(1000)),
        sa.Column("confirmation", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        *_timestamps(),
    )
    op.create_index("ix_applications_candidate_id", "applications", ["candidate_id"])
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_status", "applications", ["status"])


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("jobs")
    op.drop_table("candidates")
