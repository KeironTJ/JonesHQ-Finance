"""add onboarding state

Revision ID: e7a3c9d52f84
Revises: d6f2a8c41e73
Create Date: 2026-09-24 00:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7a3c9d52f84'
down_revision = 'd6f2a8c41e73'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('families', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'onboarding_version',
            sa.Integer(),
            server_default='1',
            nullable=False,
        ))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'onboarding_version',
            sa.Integer(),
            server_default='1',
            nullable=False,
        ))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('onboarding_version')

    with op.batch_alter_table('families', schema=None) as batch_op:
        batch_op.drop_column('onboarding_version')