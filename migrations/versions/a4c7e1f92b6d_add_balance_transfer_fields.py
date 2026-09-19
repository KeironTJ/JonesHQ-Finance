"""add balance transfer fields

Revision ID: a4c7e1f92b6d
Revises: 7a4c2e9f1b30
Create Date: 2026-09-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4c7e1f92b6d'
down_revision = '7a4c2e9f1b30'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_transfer_fee_percent', sa.Numeric(5, 2), nullable=True))

    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('linked_cc_transaction_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cc_transactions_linked_cc_transaction',
            'credit_card_transactions',
            ['linked_cc_transaction_id'], ['id'],
            ondelete='SET NULL'
        )


def downgrade():
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cc_transactions_linked_cc_transaction', type_='foreignkey')
        batch_op.drop_column('linked_cc_transaction_id')

    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.drop_column('default_transfer_fee_percent')
