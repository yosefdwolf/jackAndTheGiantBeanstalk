"""longer event names

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-11-08 23:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "picture check failed" and "kept the best try" didn't fit in 16, so those events were never saved
    op.alter_column('book_events', 'event', type_=sa.String(32), existing_type=sa.String(16))


def downgrade() -> None:
    op.alter_column('book_events', 'event', type_=sa.String(16), existing_type=sa.String(32))
