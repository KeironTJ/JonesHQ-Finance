"""add_is_fixed_to_transactions

Revision ID: 0ebbfea31600
Revises: 73095de0cc40
Create Date: 2026-01-28 09:03:46.196224

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0ebbfea31600'
down_revision = '73095de0cc40'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_fixed column to transactions table
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_fixed', sa.Boolean(), nullable=True))
    
    # Set default value for existing records
    op.execute('UPDATE transactions SET is_fixed = 0 WHERE is_fixed IS NULL')
    
    # Make column non-nullable
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('is_fixed', nullable=False, server_default='0')


def downgrade():
    # Remove is_fixed column from transactions table
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('is_fixed')
