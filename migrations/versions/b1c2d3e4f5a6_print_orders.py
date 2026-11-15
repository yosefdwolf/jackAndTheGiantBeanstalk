"""print orders

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-11-15 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

Json = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        'print_orders',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('book_id', sa.String(16), sa.ForeignKey('books.id'), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('address', Json, nullable=False),
        sa.Column('shipping_level', sa.String(16), nullable=False),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('lulu_cost_cents', sa.Integer(), nullable=False),
        sa.Column('quote', Json),
        sa.Column('lulu_job_id', sa.String(32)),
        sa.Column('lulu_status', sa.String(32)),
        sa.Column('lulu_message', sa.Text()),
        sa.Column('tracking', Json),
        sa.Column('error', sa.Text()),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('placed_at', sa.DateTime(timezone=True)),
        sa.Column('checked_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_print_orders_book_id', 'print_orders', ['book_id'])
    op.create_index('ix_print_orders_user_id', 'print_orders', ['user_id'])
    op.create_index('ix_print_orders_status', 'print_orders', ['status'])
    op.create_index('ix_print_orders_created_at', 'print_orders', ['created_at'])


def downgrade() -> None:
    op.drop_table('print_orders')
