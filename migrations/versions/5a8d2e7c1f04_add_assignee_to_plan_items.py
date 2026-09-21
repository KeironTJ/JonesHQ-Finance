"""add assignee to plan items

Revision ID: 5a8d2e7c1f04
Revises: 4f2a8c1d9e70
Create Date: 2026-09-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '5a8d2e7c1f04'
down_revision = '4f2a8c1d9e70'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('assigned_to', sa.String(length=100), nullable=True))
        batch_op.create_index('ix_plan_items_assigned_to', ['assigned_to'], unique=False)


def downgrade():
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.drop_index('ix_plan_items_assigned_to')
        batch_op.drop_column('assigned_to')
