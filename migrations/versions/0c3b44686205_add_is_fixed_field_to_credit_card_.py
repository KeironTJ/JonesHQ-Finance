"""Add is_fixed field to credit_card_transactions

Revision ID: 0c3b44686205
Revises: 8bed7c642c1f
Create Date: 2026-01-28 07:40:44.004292

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c3b44686205'
down_revision = '8bed7c642c1f'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_fixed column to credit_card_transactions
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_fixed', sa.Boolean(), nullable=True, server_default='0'))


def downgrade():
    # Remove is_fixed column
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.drop_column('is_fixed')
