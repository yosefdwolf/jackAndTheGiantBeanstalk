"""scenes; where each page's words went

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-11-08 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('scenes',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('story_key', sa.String(length=64), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('image', sa.LargeBinary().with_variant(postgresql.BYTEA(), 'postgresql'), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('cost', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scenes_key'), 'scenes', ['key'], unique=False)
    op.create_index(op.f('ix_scenes_story_key'), 'scenes', ['story_key'], unique=False)
    op.add_column('images', sa.Column('text_zone', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('images', 'text_zone')
    op.drop_index(op.f('ix_scenes_story_key'), table_name='scenes')
    op.drop_index(op.f('ix_scenes_key'), table_name='scenes')
    op.drop_table('scenes')
