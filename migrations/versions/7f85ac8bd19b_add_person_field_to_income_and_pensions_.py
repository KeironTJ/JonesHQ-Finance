"""Add person field to income and pensions, add transaction linking

Revision ID: 7f85ac8bd19b
Revises: dc41d8efc05f
Create Date: 2026-02-02 15:58:00.206659

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f85ac8bd19b'
down_revision = 'dc41d8efc05f'
branch_labels = None
depends_on = None


def upgrade():
    # Add person column to pensions table
    with op.batch_alter_table('pensions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('person', sa.String(length=50), nullable=False, server_default='Keiron'))
    
    # Add person column to income table
    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.add_column(sa.Column('person', sa.String(length=50), nullable=False, server_default='Keiron'))
        batch_op.add_column(sa.Column('deposit_account_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('transaction_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_income_deposit_account', 'accounts', ['deposit_account_id'], ['id'])
        batch_op.create_foreign_key('fk_income_transaction', 'transactions', ['transaction_id'], ['id'])


def downgrade():
    # Remove columns from income table
    with op.batch_alter_table('income', schema=None) as batch_op:
        batch_op.drop_constraint('fk_income_transaction', type_='foreignkey')
        batch_op.drop_constraint('fk_income_deposit_account', type_='foreignkey')
        batch_op.drop_column('transaction_id')
        batch_op.drop_column('deposit_account_id')
        batch_op.drop_column('person')
    
    # Remove person column from pensions table
    with op.batch_alter_table('pensions', schema=None) as batch_op:
        batch_op.drop_column('person')
