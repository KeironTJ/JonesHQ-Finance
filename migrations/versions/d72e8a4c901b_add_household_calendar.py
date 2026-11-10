"""Add household calendar events.

Revision ID: d72e8a4c901b
Revises: c81d4e6f9a20
"""
from alembic import op
import sqlalchemy as sa


revision = 'd72e8a4c901b'
down_revision = 'c81d4e6f9a20'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'calendar_events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('creator_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('location', sa.String(200), nullable=False, server_default=''),
        sa.Column('all_day', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('starts_on', sa.Date(), nullable=False),
        sa.Column('ends_on', sa.Date(), nullable=False),
        sa.Column('starts_at', sa.DateTime()),
        sa.Column('ends_at', sa.DateTime()),
        sa.Column('visibility', sa.String(10), nullable=False, server_default='shared'),
        sa.Column('edit_policy', sa.String(10), nullable=False, server_default='creator'),
        sa.Column('delete_policy', sa.String(10), nullable=False, server_default='creator'),
        sa.Column('edit_members', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('delete_members', sa.JSON(), nullable=False, server_default='[]'),
        sa.CheckConstraint("visibility IN ('shared', 'private')", name='ck_calendar_visibility'),
        sa.CheckConstraint("edit_policy IN ('creator', 'selected', 'household')", name='ck_calendar_edit_policy'),
        sa.CheckConstraint("delete_policy IN ('creator', 'selected', 'household')", name='ck_calendar_delete_policy'),
        sa.CheckConstraint('ends_on >= starts_on', name='ck_calendar_dates'),
        sa.CheckConstraint(
            '(all_day AND starts_at IS NULL AND ends_at IS NULL) OR '
            '(NOT all_day AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at > starts_at)',
            name='ck_calendar_times',
        ),
    )
    op.create_index('ix_calendar_events_family_id', 'calendar_events', ['family_id'])
    op.create_index('ix_calendar_events_creator_membership_id', 'calendar_events', ['creator_membership_id'])


def downgrade():
    op.drop_table('calendar_events')
