"""add recurring task intervals

Revision ID: b83e10d5f927
Revises: a72d09c4e816
"""
from alembic import op
import sqlalchemy as sa


revision = 'b83e10d5f927'
down_revision = 'a72d09c4e816'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('household_tasks') as batch:
        batch.add_column(sa.Column('recurrence', sa.String(10), nullable=False, server_default='none'))
        batch.add_column(sa.Column('missed_policy', sa.String(10), nullable=False, server_default='skip'))
        batch.add_column(sa.Column('repeat_active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('series_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('period_start', sa.Date(), nullable=True))
        batch.add_column(sa.Column('expired', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key('fk_household_tasks_series_id', 'household_tasks', ['series_id'], ['id'], ondelete='SET NULL')
        batch.create_index('ix_household_tasks_series_id', ['series_id'])
        batch.create_unique_constraint('uq_task_series_period', ['series_id', 'period_start'])
        batch.create_check_constraint('ck_task_recurrence', "recurrence IN ('none', 'daily', 'weekly')")
        batch.create_check_constraint('ck_task_missed_policy', "missed_policy IN ('skip', 'backlog')")


def downgrade():
    with op.batch_alter_table('household_tasks') as batch:
        batch.drop_constraint('ck_task_missed_policy', type_='check')
        batch.drop_constraint('ck_task_recurrence', type_='check')
        batch.drop_constraint('uq_task_series_period', type_='unique')
        batch.drop_index('ix_household_tasks_series_id')
        batch.drop_constraint('fk_household_tasks_series_id', type_='foreignkey')
        for column in ('expired', 'period_start', 'series_id', 'repeat_active', 'missed_policy', 'recurrence'):
            batch.drop_column(column)
