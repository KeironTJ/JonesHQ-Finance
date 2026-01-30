"""create expense calendar entries

Revision ID: d9a1f4b2c7e1
Revises: e346d4d6e8f1
Create Date: 2026-01-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9a1f4b2c7e1'
down_revision = 'e346d4d6e8f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'expense_calendar_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('assigned_to', sa.String(length=100), nullable=True),
        sa.Column('expense_id', sa.Integer(), sa.ForeignKey('expenses.id'), nullable=True),
        sa.Column('amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_constraint('fk_expense_calendar_expense_id', 'expense_calendar_entries', type_='foreignkey')
    op.drop_table('expense_calendar_entries')
