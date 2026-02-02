"""Add recurring income table

Revision ID: 13cd1bc1a867
Revises: 7f85ac8bd19b
Create Date: 2026-02-02 18:42:39.009839

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '13cd1bc1a867'
down_revision = '7f85ac8bd19b'
branch_labels = None
depends_on = None


def upgrade():
    # Create recurring_income table
    op.create_table('recurring_income',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('person', sa.String(length=50), nullable=False, server_default='Keiron'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('pay_day', sa.Integer(), nullable=False),
        sa.Column('last_generated_date', sa.Date(), nullable=True),
        sa.Column('gross_annual_income', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('employer_pension_percent', sa.Numeric(precision=5, scale=2), server_default='0'),
        sa.Column('employee_pension_percent', sa.Numeric(precision=5, scale=2), server_default='0'),
        sa.Column('tax_code', sa.String(length=10), nullable=False),
        sa.Column('avc', sa.Numeric(precision=10, scale=2), server_default='0'),
        sa.Column('other_deductions', sa.Numeric(precision=10, scale=2), server_default='0'),
        sa.Column('deposit_account_id', sa.Integer(), nullable=True),
        sa.Column('auto_create_transaction', sa.Boolean(), server_default='1'),
        sa.Column('source', sa.String(length=100), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['deposit_account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('recurring_income')
