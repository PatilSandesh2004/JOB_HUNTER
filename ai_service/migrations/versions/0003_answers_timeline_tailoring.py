"""Screening answer bank; application timeline, open questions and tailored resume.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with a default fills existing rows; no table rebuild needed on SQLite.
    empty = sa.text("'[]'")
    op.add_column("applications", sa.Column("events", sa.JSON(), nullable=False, server_default=empty))
    op.add_column("applications", sa.Column("questions", sa.JSON(), nullable=False, server_default=empty))
    op.add_column("applications", sa.Column("tailored_resume_path", sa.String(1000)))
    op.add_column("applications", sa.Column("resume_report", sa.JSON()))

    op.create_table(
        "screening_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("question_key", sa.String(300), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_screening_answers_question_key", "screening_answers", ["question_key"], unique=True)


def downgrade() -> None:
    op.drop_table("screening_answers")
    for column in ("resume_report", "tailored_resume_path", "questions", "events"):
        op.drop_column("applications", column)
