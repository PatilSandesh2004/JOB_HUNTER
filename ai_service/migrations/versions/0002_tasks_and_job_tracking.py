"""Durable agent task queue; job closed/checked tracking; sortable match score.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("overall_match", sa.Float()))
    op.add_column("jobs", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("last_checked_at", sa.DateTime(timezone=True)))
    op.create_index("ix_jobs_overall_match", "jobs", ["overall_match"])

    # Backfill the sortable score from the stored match JSON.
    jobs = sa.table(
        "jobs", sa.column("id", sa.String), sa.column("match", sa.JSON), sa.column("overall_match", sa.Float)
    )
    bind = op.get_bind()
    for job_id, match in bind.execute(sa.select(jobs.c.id, jobs.c.match)).all():
        score = (match or {}).get("overall_match")
        if score is not None:
            bind.execute(jobs.update().where(jobs.c.id == job_id).values(overall_match=float(score)))

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_tasks_due", "agent_tasks", ["status", "run_after"])
    op.create_index("ix_agent_tasks_application_id", "agent_tasks", ["application_id"])


def downgrade() -> None:
    op.drop_table("agent_tasks")
    op.drop_index("ix_jobs_overall_match", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("last_checked_at")
        batch.drop_column("closed_at")
        batch.drop_column("overall_match")
