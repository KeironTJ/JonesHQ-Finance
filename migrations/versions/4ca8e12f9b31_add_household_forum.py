"""Add household forum.

Revision ID: 4ca8e12f9b31
Revises: d4b8f2a61c37
"""
from alembic import op
import sqlalchemy as sa


revision = '4ca8e12f9b31'
down_revision = 'd4b8f2a61c37'
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
    ]


def _membership(name):
    return sa.Column(name, sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True)


def upgrade():
    op.create_table(
        'forum_categories', *_base(), sa.Column('name', sa.String(80), nullable=False),
        sa.UniqueConstraint('family_id', 'name', name='uq_forum_category_name'),
    )
    op.create_table(
        'forum_topics', *_base(),
        sa.Column('category_id', sa.Integer(), sa.ForeignKey('forum_categories.id'), nullable=True),
        _membership('creator_membership_id'), sa.Column('title', sa.String(200), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'forum_posts', *_base(),
        sa.Column('topic_id', sa.Integer(), sa.ForeignKey('forum_topics.id', ondelete='CASCADE'), nullable=False),
        _membership('creator_membership_id'), sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('edited_at', sa.DateTime(), nullable=True),
    )
    op.create_table(
        'forum_attachments', *_base(),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False), sa.Column('content', sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        'forum_reactions', *_base(),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False),
        _membership('membership_id'), sa.UniqueConstraint('post_id', 'membership_id', name='uq_forum_reaction_member'),
    )
    op.create_table(
        'forum_notifications', *_base(),
        _membership('membership_id'),
        sa.Column('post_id', sa.Integer(), sa.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False), sa.Column('read_at', sa.DateTime(), nullable=True),
    )
    for table, columns in (
        ('forum_categories', ('family_id',)),
        ('forum_topics', ('family_id', 'category_id', 'updated_at')),
        ('forum_posts', ('family_id', 'topic_id')),
        ('forum_attachments', ('family_id', 'post_id')),
        ('forum_reactions', ('family_id', 'post_id', 'membership_id')),
        ('forum_notifications', ('family_id', 'post_id', 'membership_id')),
    ):
        for column in columns:
            op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    for table in (
        'forum_notifications', 'forum_reactions', 'forum_attachments',
        'forum_posts', 'forum_topics', 'forum_categories',
    ):
        op.drop_table(table)
