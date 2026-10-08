"""Remember which jobs a strong-match alert was sent for, so none is announced twice.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("notified_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("jobs", "notified_at")
