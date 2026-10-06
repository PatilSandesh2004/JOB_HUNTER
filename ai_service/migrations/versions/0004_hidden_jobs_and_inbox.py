"""Hidden ("not interested") jobs; inbox messages already processed.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("hidden_at", sa.DateTime(timezone=True)))
    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.String(500)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inbox_messages")
    op.drop_column("jobs", "hidden_at")
