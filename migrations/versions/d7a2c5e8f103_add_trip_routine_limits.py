"""Add site-admin trip routine limits.

Revision ID: d7a2c5e8f103
Revises: c6a8e1f3b5d7
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7a2c5e8f103'
down_revision = 'c6a8e1f3b5d7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'trip_planning_max_days', sa.Integer(), nullable=False, server_default='1800',
        ))
        batch_op.add_column(sa.Column(
            'trip_active_routine_limit', sa.Integer(), nullable=False, server_default='25',
        ))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('trip_active_routine_limit')
        batch_op.drop_column('trip_planning_max_days')
