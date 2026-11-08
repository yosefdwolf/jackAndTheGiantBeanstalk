"""activity

Revision ID: e4b19a7c2d51
Revises: c86032c875dc
Create Date: 2026-11-07 23:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e4b19a7c2d51'
down_revision: Union[str, None] = 'c86032c875dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('activity',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('book_id', sa.String(length=16), nullable=True),
    sa.Column('level', sa.String(length=8), nullable=False),
    sa.Column('step', sa.String(length=64), nullable=False),
    sa.Column('event', sa.String(length=32), nullable=False),
    sa.Column('fields', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activity_at'), 'activity', ['at'], unique=False)
    op.create_index(op.f('ix_activity_user_id'), 'activity', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_user_id'), table_name='activity')
    op.drop_index(op.f('ix_activity_at'), table_name='activity')
    op.drop_table('activity')
