"""page words saved with the picture

Revision ID: a9b8c7d6e5f4
Revises: e1f2a3b4c5d6
Create Date: 2026-11-15 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A book read its words from today's story file, so renumbering a story shifted older books' words a page
    op.add_column('images', sa.Column('words', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('images', 'words')
