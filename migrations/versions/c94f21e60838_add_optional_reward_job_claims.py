"""add optional reward job claims

Revision ID: c94f21e60838
Revises: b83e10d5f927
"""
from alembic import op
import sqlalchemy as sa


revision = 'c94f21e60838'
down_revision = 'b83e10d5f927'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('household_tasks') as batch:
        batch.add_column(sa.Column('claim_required', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('claimed_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('household_tasks') as batch:
        batch.drop_column('claimed_at')
        batch.drop_column('claim_required')
