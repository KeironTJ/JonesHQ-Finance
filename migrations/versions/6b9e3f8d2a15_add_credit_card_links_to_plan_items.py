"""add credit card links to plan items

Revision ID: 6b9e3f8d2a15
Revises: 5a8d2e7c1f04
Create Date: 2026-09-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '6b9e3f8d2a15'
down_revision = '5a8d2e7c1f04'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.add_column(sa.Column('credit_card_transaction_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_plan_items_credit_card_transaction_id', ['credit_card_transaction_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_plan_items_credit_card_transaction_id',
            'credit_card_transactions',
            ['credit_card_transaction_id'],
            ['id'],
        )


def downgrade():
    with op.batch_alter_table('plan_items', schema=None) as batch_op:
        batch_op.drop_constraint('fk_plan_items_credit_card_transaction_id', type_='foreignkey')
        batch_op.drop_index('ix_plan_items_credit_card_transaction_id')
        batch_op.drop_column('credit_card_transaction_id')
