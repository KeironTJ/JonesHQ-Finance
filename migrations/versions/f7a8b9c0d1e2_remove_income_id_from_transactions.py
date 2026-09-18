"""remove reverse income link from transactions

Revision ID: f7a8b9c0d1e2
Revises: e8f9a2b3c4d5
Create Date: 2026-09-18

"""
from alembic import op


revision = 'f7a8b9c0d1e2'
down_revision = 'e8f9a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_transactions_income_id', type_='foreignkey')
        batch_op.drop_column('income_id')


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        import sqlalchemy as sa
        batch_op.add_column(sa.Column('income_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_transactions_income_id', 'income', ['income_id'], ['id']
        )
