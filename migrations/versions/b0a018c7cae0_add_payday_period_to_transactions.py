"""add_payday_period_to_transactions

Revision ID: b0a018c7cae0
Revises: bb129c35254e
Create Date: 2026-01-29 13:45:18.780372

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b0a018c7cae0'
down_revision = 'bb129c35254e'
branch_labels = None
depends_on = None


def upgrade():
    # Add payday_period column to transactions table
    op.add_column('transactions', sa.Column('payday_period', sa.String(7), nullable=True))
    
    # Add index for faster filtering
    op.create_index('ix_transactions_payday_period', 'transactions', ['payday_period'])


def downgrade():
    # Remove index and column
    op.drop_index('ix_transactions_payday_period', 'transactions')
    op.drop_column('transactions', 'payday_period')
