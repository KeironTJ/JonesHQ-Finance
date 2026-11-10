"""Add household rewards and once-only point entries.

Revision ID: c27d3f9b456a
Revises: b16c2e8a345f
"""
from alembic import op
import sqlalchemy as sa


revision = 'c27d3f9b456a'
down_revision = 'b16c2e8a345f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'household_rewards',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('title', sa.String(128), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('points_cost', sa.Integer(), nullable=False),
        sa.Column('icon', sa.String(30), nullable=False, server_default='gift'),
        sa.Column('available', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint('points_cost BETWEEN 1 AND 10000', name='ck_household_reward_cost'),
    )
    op.create_table(
        'reward_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('household_tasks.id', ondelete='SET NULL'), unique=True),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('reviewer_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(12), nullable=False, server_default='open'),
        sa.Column('submitted_at', sa.DateTime()),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('review_note', sa.Text(), nullable=False, server_default=''),
        sa.CheckConstraint('points BETWEEN 1 AND 1000', name='ck_reward_job_points'),
        sa.CheckConstraint("state IN ('open','submitted','approved','closed')", name='ck_reward_job_state'),
    )
    op.create_table(
        'reward_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('reward_id', sa.Integer(), sa.ForeignKey('household_rewards.id', ondelete='SET NULL')),
        sa.Column('reviewer_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('title', sa.String(128), nullable=False),
        sa.Column('points_cost', sa.Integer(), nullable=False),
        sa.Column('request_key', sa.String(36), nullable=False),
        sa.Column('state', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('review_note', sa.Text(), nullable=False, server_default=''),
        sa.CheckConstraint('points_cost BETWEEN 1 AND 10000', name='ck_reward_request_cost'),
        sa.CheckConstraint("state IN ('pending','approved','declined')", name='ck_reward_request_state'),
        sa.UniqueConstraint('membership_id', 'request_key', name='uq_reward_request_key'),
    )
    op.create_table(
        'reward_points',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('actor_membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('reward_jobs.id', ondelete='SET NULL')),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('reward_requests.id', ondelete='SET NULL')),
        sa.Column('kind', sa.String(10), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('description', sa.String(256), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'earned' AND points > 0) OR (kind = 'reserved' AND points < 0) "
            "OR (kind = 'returned' AND points > 0)", name='ck_reward_points_kind',
        ),
        sa.UniqueConstraint('job_id', name='uq_reward_points_job'),
        sa.UniqueConstraint('request_id', 'kind', name='uq_reward_points_request_kind'),
    )
    op.create_table(
        'reward_goals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL'), unique=True),
        sa.Column('reward_id', sa.Integer(), sa.ForeignKey('household_rewards.id', ondelete='SET NULL')),
    )
    for table, columns in (
        ('household_rewards', ('family_id',)),
        ('reward_jobs', ('family_id', 'membership_id')),
        ('reward_requests', ('family_id', 'membership_id', 'reward_id')),
        ('reward_points', ('family_id', 'membership_id')),
        ('reward_goals', ('family_id',)),
    ):
        for column in columns:
            op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    for table in ('reward_points', 'reward_requests', 'reward_goals', 'reward_jobs', 'household_rewards'):
        op.drop_table(table)
