"""Add household activities, suggestions and attendees.

Revision ID: a05b1d7f234e
Revises: f94a0c6e123d
"""
from alembic import op
import sqlalchemy as sa


revision = 'a05b1d7f234e'
down_revision = 'f94a0c6e123d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'activities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('creator_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('reviewer_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('comments', sa.Text(), nullable=False, server_default=''),
        sa.Column('location', sa.String(200), nullable=False, server_default=''),
        sa.Column('all_day', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('starts_on', sa.Date(), nullable=False),
        sa.Column('ends_on', sa.Date(), nullable=False),
        sa.Column('starts_at', sa.DateTime()),
        sa.Column('ends_at', sa.DateTime()),
        sa.Column('recurrence', sa.String(10), nullable=False, server_default='none'),
        sa.Column('repeat_until', sa.Date()),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_activity_status'),
        sa.CheckConstraint("recurrence IN ('none', 'weekly')", name='ck_activity_recurrence'),
        sa.CheckConstraint(
            "(recurrence = 'none' AND repeat_until IS NULL) OR "
            "(recurrence = 'weekly' AND repeat_until IS NOT NULL AND repeat_until >= starts_on)",
            name='ck_activity_repeat_until',
        ),
        sa.CheckConstraint('ends_on >= starts_on', name='ck_activity_dates'),
        sa.CheckConstraint(
            '(all_day AND starts_at IS NULL AND ends_at IS NULL) OR '
            '(NOT all_day AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at > starts_at)',
            name='ck_activity_times',
        ),
    )
    for column in ('family_id', 'creator_membership_id', 'starts_on'):
        op.create_index(f'ix_activities_{column}', 'activities', [column])
    op.create_table(
        'activity_attendees',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('activity_id', sa.Integer(), sa.ForeignKey('activities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('activity_id', 'membership_id', name='uq_activity_attendee'),
    )
    for column in ('family_id', 'activity_id', 'membership_id'):
        op.create_index(f'ix_activity_attendees_{column}', 'activity_attendees', [column])


def downgrade():
    op.drop_table('activity_attendees')
    op.drop_table('activities')
