"""stories, characters, character pictures

Revision ID: a8d3e1f09c2b
Revises: f7a2c3d4e5b6
Create Date: 2026-11-08 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8d3e1f09c2b'
down_revision: Union[str, None] = 'f7a2c3d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ID = sa.BigInteger().with_variant(sa.Integer(), 'sqlite')


def upgrade() -> None:
    op.create_table('stories',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('file_hash', sa.String(length=16), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('characters',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('story_id', ID, nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('pin', sa.String(length=160), nullable=True),
    sa.Column('picture_id', ID, nullable=True),
    sa.ForeignKeyConstraint(['story_id'], ['stories.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('story_id', 'key')
    )
    op.create_index(op.f('ix_characters_story_id'), 'characters', ['story_id'], unique=False)
    op.create_table('character_pictures',
    sa.Column('id', ID, autoincrement=True, nullable=False),
    sa.Column('character_id', ID, nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('image', sa.LargeBinary().with_variant(postgresql.BYTEA(), 'postgresql'), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('cost', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id']),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('character_id', 'name')
    )
    op.create_index(op.f('ix_character_pictures_character_id'), 'character_pictures', ['character_id'], unique=False)
    with op.batch_alter_table('characters') as batch:  # characters <-> pictures point at each other
        batch.create_foreign_key('fk_characters_picture_id', 'character_pictures', ['picture_id'], ['id'])
    with op.batch_alter_table('books') as batch:
        batch.add_column(sa.Column('story_id', ID, nullable=True))
        batch.create_index(batch.f('ix_books_story_id'), ['story_id'], unique=False)
        batch.create_foreign_key('fk_books_story_id', 'stories', ['story_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('books') as batch:
        batch.drop_constraint('fk_books_story_id', type_='foreignkey')
        batch.drop_index(batch.f('ix_books_story_id'))
        batch.drop_column('story_id')
    with op.batch_alter_table('characters') as batch:
        batch.drop_constraint('fk_characters_picture_id', type_='foreignkey')
    op.drop_index(op.f('ix_character_pictures_character_id'), table_name='character_pictures')
    op.drop_table('character_pictures')
    op.drop_index(op.f('ix_characters_story_id'), table_name='characters')
    op.drop_table('characters')
    op.drop_table('stories')
