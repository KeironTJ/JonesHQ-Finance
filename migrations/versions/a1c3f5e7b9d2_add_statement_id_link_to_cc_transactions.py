"""add statement_id link to cc transactions

Revision ID: a1c3f5e7b9d2
Revises: 8b97863c529e
Create Date: 2026-02-23 00:00:00.000000

Links each generated Payment transaction back to the Interest (statement)
transaction that triggered it, via a nullable self-referential FK.
ondelete='SET NULL' means deleting a statement simply NULLs the FK on the
payment rather than cascading the delete at the DB level (deletion logic
is handled at the service layer where is_fixed can be respected).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c3f5e7b9d2'
down_revision = '8b97863c529e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('statement_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cc_transaction_statement_id',
            'credit_card_transactions',
            ['statement_id'],
            ['id'],
            ondelete='SET NULL'
        )


def downgrade():
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cc_transaction_statement_id', type_='foreignkey')
        batch_op.drop_column('statement_id')
