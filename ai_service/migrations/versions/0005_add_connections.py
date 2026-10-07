"""add connections

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('connections',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('candidate_id', sa.String(length=36), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('company', sa.String(length=200), nullable=False),
    sa.Column('position', sa.String(length=200), nullable=False),
    sa.Column('connected_on', sa.String(length=50), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_connections_candidate_id'), 'connections', ['candidate_id'], unique=False)
    op.create_index(op.f('ix_connections_company'), 'connections', ['company'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_connections_company'), table_name='connections')
    op.drop_index(op.f('ix_connections_candidate_id'), table_name='connections')
    op.drop_table('connections')
