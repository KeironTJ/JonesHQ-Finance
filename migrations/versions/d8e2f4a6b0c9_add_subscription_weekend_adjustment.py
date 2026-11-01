"""Add subscription weekend and bank holiday adjustment.

Revision ID: d8e2f4a6b0c9
Revises: c7d9e1a3b5f7
"""
from alembic import op
import sqlalchemy as sa


revision = 'd8e2f4a6b0c9'
down_revision = 'c7d9e1a3b5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'subscriptions',
        sa.Column(
            'weekend_adjustment', sa.String(length=10),
            nullable=False, server_default='none',
        ),
    )


def downgrade():
    with op.batch_alter_table('subscriptions') as batch_op:
        batch_op.drop_column('weekend_adjustment')
