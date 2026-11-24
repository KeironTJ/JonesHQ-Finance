"""Add forum post pins and household mentions.

Revision ID: 91be0a73d426
Revises: 4ca8e12f9b31
"""
from alembic import op
import sqlalchemy as sa

revision = '91be0a73d426'
down_revision = '4ca8e12f9b31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('forum_posts') as batch:
        batch.add_column(sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table('forum_notifications') as batch:
        batch.add_column(sa.Column('mentioned', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        'forum_mentions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('post_id', 'membership_id', name='uq_forum_mention_member'),
    )
    for column in ('family_id', 'post_id', 'membership_id'):
        op.create_index(f'ix_forum_mentions_{column}', 'forum_mentions', [column])


def downgrade():
    op.drop_table('forum_mentions')
    with op.batch_alter_table('forum_notifications') as batch:
        batch.drop_column('mentioned')
    with op.batch_alter_table('forum_posts') as batch:
        batch.drop_column('pinned')
