"""Richer job requirements: experience range, nice-to-have skills, salary period.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("experience_max", sa.Float()))
    op.add_column("jobs", sa.Column("preferred_skills", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("jobs", sa.Column("salary_period", sa.String(8)))


def downgrade() -> None:
    op.drop_column("jobs", "salary_period")
    op.drop_column("jobs", "preferred_skills")
    op.drop_column("jobs", "experience_max")
