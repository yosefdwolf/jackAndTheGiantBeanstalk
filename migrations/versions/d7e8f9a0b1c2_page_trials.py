"""page trials

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-11-08 21:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('page_trials',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('story_key', sa.String(length=64), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('how', sa.String(length=16), nullable=False),
    sa.Column('book_id', sa.String(length=16), nullable=False),
    sa.Column('scene_id', sa.Integer(), nullable=True),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('image', sa.LargeBinary().with_variant(postgresql.BYTEA(), 'postgresql'), nullable=False),
    sa.Column('cost', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_page_trials_story_key'), 'page_trials', ['story_key'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_page_trials_story_key'), table_name='page_trials')
    op.drop_table('page_trials')
