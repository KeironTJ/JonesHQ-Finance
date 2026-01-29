"""swap_transaction_amount_signs

Revision ID: 87ac9611cb21
Revises: b0a018c7cae0
Create Date: 2026-01-29 14:26:17.712260

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '87ac9611cb21'
down_revision = 'b0a018c7cae0'
branch_labels = None
depends_on = None


def upgrade():
    # Swap the sign of all transaction amounts
    # Old convention: Income = negative, Expenses = positive
    # New convention: Income = positive, Expenses = negative
    op.execute('UPDATE transactions SET amount = amount * -1')


def downgrade():
    # Reverse the sign swap
    op.execute('UPDATE transactions SET amount = amount * -1')
