"""Add monthly_account_balances cache table

Revision ID: dc41d8efc05f
Revises: d39d6cc6f6b2
Create Date: 2026-02-02 13:40:34.399203

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'dc41d8efc05f'
down_revision = 'd39d6cc6f6b2'
branch_labels = None
depends_on = None


def upgrade():
    # Create monthly_account_balances table
    op.create_table(
        'monthly_account_balances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('year_month', sa.String(length=7), nullable=False),
        sa.Column('actual_balance', sa.Float(), nullable=False),
        sa.Column('projected_balance', sa.Float(), nullable=False),
        sa.Column('last_calculated', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'year_month', name='uix_account_month')
    )
    
    # Create index for efficient lookups
    op.create_index(
        'idx_account_year_month',
        'monthly_account_balances',
        ['account_id', 'year_month'],
        unique=False
    )


def downgrade():
    # Drop index first
    op.drop_index('idx_account_year_month', table_name='monthly_account_balances')
    
    # Drop table
    op.drop_table('monthly_account_balances')
