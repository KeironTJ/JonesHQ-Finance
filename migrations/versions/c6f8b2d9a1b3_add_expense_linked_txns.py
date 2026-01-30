"""Add credit_card_transaction_id and bank_transaction_id to expenses

Revision ID: c6f8b2d9a1b3
Revises: bb129c35254e
Create Date: 2026-01-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6f8b2d9a1b3'
down_revision = 'bb129c35254e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credit_card_transaction_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('bank_transaction_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_expenses_credit_card_txn_id', 'credit_card_transactions', ['credit_card_transaction_id'], ['id'])
        batch_op.create_foreign_key('fk_expenses_bank_txn_id', 'transactions', ['bank_transaction_id'], ['id'])


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_expenses_bank_txn_id', type_='foreignkey')
        batch_op.drop_constraint('fk_expenses_credit_card_txn_id', type_='foreignkey')
        batch_op.drop_column('bank_transaction_id')
        batch_op.drop_column('credit_card_transaction_id')
