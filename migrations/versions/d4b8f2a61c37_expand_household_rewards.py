"""Expand household rewards: participation, recognition, limits, fulfilment,
multiple goals, achievements and chore templates.

Revision ID: d4b8f2a61c37
Revises: a7c13d8e5f20
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4b8f2a61c37'
down_revision = 'a7c13d8e5f20'
branch_labels = None
depends_on = None

OLD_KIND_CHECK = (
    "(kind = 'earned' AND points > 0) OR (kind = 'reserved' AND points < 0) "
    "OR (kind = 'returned' AND points > 0)"
)
NEW_KIND_CHECK = (
    "(kind IN ('earned','returned','bonus','milestone') AND points > 0) "
    "OR (kind IN ('reserved','deduction') AND points < 0)"
)


def _goals_table():
    metadata = sa.MetaData()
    sa.Table('families', metadata, sa.Column('id', sa.Integer(), primary_key=True))
    sa.Table('household_memberships', metadata, sa.Column('id', sa.Integer(), primary_key=True))
    sa.Table('household_rewards', metadata, sa.Column('id', sa.Integer(), primary_key=True))
    return sa.Table(
        'reward_goals', metadata,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL')),
        sa.Column('reward_id', sa.Integer(), sa.ForeignKey('household_rewards.id', ondelete='SET NULL')),
        sa.Index('ix_reward_goals_family_id', 'family_id'),
    )


def _drop_member_unique(bind):
    for constraint in sa.inspect(bind).get_unique_constraints('reward_goals'):
        if constraint['column_names'] == ['membership_id'] and constraint['name']:
            op.drop_constraint(constraint['name'], 'reward_goals', type_='unique')


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table('families') as batch:
        batch.add_column(sa.Column(
            'rewards_defaults_seeded', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
    with op.batch_alter_table('household_memberships') as batch:
        batch.add_column(sa.Column(
            'rewards_participant', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))
    with op.batch_alter_table('household_rewards') as batch:
        batch.add_column(sa.Column('category', sa.String(20), nullable=False, server_default='treat'))
        batch.add_column(sa.Column('stock', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('cooldown_days', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('member_limit', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('limit_period', sa.String(10), nullable=True))
        batch.create_check_constraint('ck_household_reward_stock', 'stock IS NULL OR stock BETWEEN 0 AND 1000')
        batch.create_check_constraint(
            'ck_household_reward_cooldown', 'cooldown_days IS NULL OR cooldown_days BETWEEN 1 AND 365',
        )
        batch.create_check_constraint(
            'ck_household_reward_limit',
            "(member_limit IS NULL AND limit_period IS NULL) OR (member_limit BETWEEN 1 AND 100 "
            "AND limit_period IN ('week','month','year','ever'))",
        )

    op.create_table(
        'reward_achievements',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('title', sa.String(64), nullable=False),
        sa.Column('description', sa.String(256), nullable=False, server_default=''),
        sa.Column('icon', sa.String(30), nullable=False, server_default='trophy'),
        sa.Column('metric', sa.String(12), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('bonus_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint(
            "metric IN ('chores','points','streak','recognition')", name='ck_reward_achievement_metric',
        ),
        sa.CheckConstraint('threshold BETWEEN 1 AND 100000', name='ck_reward_achievement_threshold'),
        sa.CheckConstraint('bonus_points BETWEEN 0 AND 1000', name='ck_reward_achievement_bonus'),
    )
    op.create_index('ix_reward_achievements_family_id', 'reward_achievements', ['family_id'])
    op.create_table(
        'reward_achievement_unlocks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column(
            'achievement_id', sa.Integer(), sa.ForeignKey('reward_achievements.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'membership_id', sa.Integer(), sa.ForeignKey('household_memberships.id', ondelete='SET NULL'),
        ),
        sa.Column('title', sa.String(64), nullable=False),
        sa.Column('icon', sa.String(30), nullable=False, server_default='trophy'),
        sa.Column('unlocked_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('achievement_id', 'membership_id', name='uq_reward_unlock_member'),
    )
    for column in ('family_id', 'achievement_id', 'membership_id'):
        op.create_index(f'ix_reward_achievement_unlocks_{column}', 'reward_achievement_unlocks', [column])
    op.create_table(
        'reward_chore_templates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.CheckConstraint('points BETWEEN 1 AND 1000', name='ck_reward_template_points'),
    )
    op.create_index('ix_reward_chore_templates_family_id', 'reward_chore_templates', ['family_id'])

    with op.batch_alter_table('reward_requests') as batch:
        batch.add_column(sa.Column('fulfilled_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('fulfilled_by_membership_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_reward_requests_fulfilled_by', 'household_memberships',
            ['fulfilled_by_membership_id'], ['id'], ondelete='SET NULL',
        )
    # Previously, approval meant the reward was handed over.
    op.execute("UPDATE reward_requests SET fulfilled_at = reviewed_at WHERE state = 'approved'")

    with op.batch_alter_table('reward_points') as batch:
        batch.add_column(sa.Column('unlock_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('category', sa.String(20), nullable=True))
        batch.create_foreign_key(
            'fk_reward_points_unlock_id', 'reward_achievement_unlocks', ['unlock_id'], ['id'], ondelete='SET NULL',
        )
        batch.create_unique_constraint('uq_reward_points_unlock', ['unlock_id'])
        batch.drop_constraint('ck_reward_points_kind', type_='check')
        batch.create_check_constraint('ck_reward_points_kind', NEW_KIND_CHECK)

    if bind.dialect.name == 'sqlite':
        # copy_from omits the unnamed one-goal-per-member unique constraint.
        with op.batch_alter_table('reward_goals', recreate='always', copy_from=_goals_table()) as batch:
            batch.create_unique_constraint('uq_reward_goal_member_reward', ['membership_id', 'reward_id'])
            batch.create_index('ix_reward_goals_membership_id', ['membership_id'])
    else:
        _drop_member_unique(bind)
        op.create_unique_constraint('uq_reward_goal_member_reward', 'reward_goals', ['membership_id', 'reward_id'])
        op.create_index('ix_reward_goals_membership_id', 'reward_goals', ['membership_id'])


def downgrade():
    bind = op.get_bind()
    # Keep each member's earliest goal, as the previous schema allowed one.
    op.execute(
        'DELETE FROM reward_goals WHERE membership_id IS NOT NULL AND id NOT IN '
        '(SELECT MIN(id) FROM reward_goals WHERE membership_id IS NOT NULL GROUP BY membership_id)'
    )
    if bind.dialect.name == 'sqlite':
        with op.batch_alter_table('reward_goals', recreate='always', copy_from=_goals_table()) as batch:
            batch.create_unique_constraint('reward_goals_membership_id_key', ['membership_id'])
    else:
        op.drop_index('ix_reward_goals_membership_id', table_name='reward_goals')
        op.drop_constraint('uq_reward_goal_member_reward', 'reward_goals', type_='unique')
        op.create_unique_constraint('reward_goals_membership_id_key', 'reward_goals', ['membership_id'])

    op.execute("UPDATE reward_points SET kind = 'earned' WHERE kind IN ('bonus', 'milestone')")
    op.execute("UPDATE reward_points SET kind = 'reserved' WHERE kind = 'deduction'")
    with op.batch_alter_table('reward_points') as batch:
        batch.drop_constraint('ck_reward_points_kind', type_='check')
        batch.create_check_constraint('ck_reward_points_kind', OLD_KIND_CHECK)
        batch.drop_constraint('uq_reward_points_unlock', type_='unique')
        batch.drop_constraint('fk_reward_points_unlock_id', type_='foreignkey')
        batch.drop_column('category')
        batch.drop_column('unlock_id')
    with op.batch_alter_table('reward_requests') as batch:
        batch.drop_constraint('fk_reward_requests_fulfilled_by', type_='foreignkey')
        batch.drop_column('fulfilled_by_membership_id')
        batch.drop_column('fulfilled_at')

    op.drop_table('reward_chore_templates')
    op.drop_table('reward_achievement_unlocks')
    op.drop_table('reward_achievements')

    with op.batch_alter_table('household_rewards') as batch:
        batch.drop_constraint('ck_household_reward_limit', type_='check')
        batch.drop_constraint('ck_household_reward_cooldown', type_='check')
        batch.drop_constraint('ck_household_reward_stock', type_='check')
        for column in ('limit_period', 'member_limit', 'cooldown_days', 'stock', 'category'):
            batch.drop_column(column)
    with op.batch_alter_table('household_memberships') as batch:
        batch.drop_column('rewards_participant')
    with op.batch_alter_table('families') as batch:
        batch.drop_column('rewards_defaults_seeded')
