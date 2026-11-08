"""shared pages

Revision ID: b3c4d5e6f7a8
Revises: a8d3e1f09c2b
Create Date: 2026-11-08 18:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a8d3e1f09c2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('shared_pages',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('story_key', sa.String(length=64), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=False),
    sa.Column('image', sa.LargeBinary().with_variant(postgresql.BYTEA(), 'postgresql'), nullable=False),
    sa.Column('cost', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('shared_pages')
