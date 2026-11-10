"""Add household task lists and tasks.

Revision ID: b16c2e8a345f
Revises: a05b1d7f234e
"""
from alembic import op
import sqlalchemy as sa


revision = 'b16c2e8a345f'
down_revision = 'a05b1d7f234e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'task_lists',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('creator_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(128), nullable=False),
        sa.Column('visibility', sa.String(10), nullable=False, server_default='personal'),
        sa.Column('icon', sa.String(30), nullable=False, server_default='list-check'),
        sa.Column('colour', sa.String(20), nullable=False, server_default='primary'),
        sa.CheckConstraint("visibility IN ('personal', 'shared')", name='ck_task_list_visibility'),
    )
    for column in ('family_id', 'creator_membership_id'):
        op.create_index(f'ix_task_lists_{column}', 'task_lists', [column])
    op.create_table(
        'household_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('list_id', sa.Integer(), sa.ForeignKey('task_lists.id', ondelete='CASCADE'), nullable=False),
        sa.Column('creator_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('assigned_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('completed_by_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('priority', sa.String(10), nullable=False, server_default='medium'),
        sa.Column('due_date', sa.Date()),
        sa.Column('due_time', sa.Time()),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('completed_at', sa.DateTime()),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name='ck_household_task_priority'),
        sa.CheckConstraint('due_time IS NULL OR due_date IS NOT NULL', name='ck_household_task_due_time'),
        sa.CheckConstraint(
            '(completed AND completed_at IS NOT NULL) OR '
            '(NOT completed AND completed_at IS NULL AND completed_by_membership_id IS NULL)',
            name='ck_household_task_completion',
        ),
    )
    for column in ('family_id', 'list_id', 'assigned_membership_id', 'due_date'):
        op.create_index(f'ix_household_tasks_{column}', 'household_tasks', [column])


def downgrade():
    op.drop_table('household_tasks')
    op.drop_table('task_lists')
