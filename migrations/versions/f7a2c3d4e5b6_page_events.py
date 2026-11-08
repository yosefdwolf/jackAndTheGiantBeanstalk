"""page events

Revision ID: f7a2c3d4e5b6
Revises: e4b19a7c2d51
Create Date: 2026-11-08 00:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7a2c3d4e5b6'
down_revision: Union[str, None] = 'e4b19a7c2d51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('page_events',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('visitor', sa.String(length=24), nullable=False),
    sa.Column('session', sa.String(length=24), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('path', sa.String(length=128), nullable=False),
    sa.Column('props', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_page_events_at'), 'page_events', ['at'], unique=False)
    op.create_index(op.f('ix_page_events_visitor'), 'page_events', ['visitor'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_page_events_visitor'), table_name='page_events')
    op.drop_index(op.f('ix_page_events_at'), table_name='page_events')
    op.drop_table('page_events')
