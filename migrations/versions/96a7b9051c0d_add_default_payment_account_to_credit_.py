"""add_default_payment_account_to_credit_cards

Revision ID: 96a7b9051c0d
Revises: 0ebbfea31600
Create Date: 2026-01-28 10:36:12.015656

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '96a7b9051c0d'
down_revision = '0ebbfea31600'
branch_labels = None
depends_on = None


def upgrade():
    # Add default_payment_account_id column to credit_cards table
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_payment_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_credit_cards_default_payment_account', 'accounts', ['default_payment_account_id'], ['id'])


def downgrade():
    # Remove default_payment_account_id column from credit_cards table
    with op.batch_alter_table('credit_cards', schema=None) as batch_op:
        batch_op.drop_constraint('fk_credit_cards_default_payment_account', type_='foreignkey')
        batch_op.drop_column('default_payment_account_id')
