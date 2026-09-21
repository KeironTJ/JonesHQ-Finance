"""add vendor_id to credit card transactions

Revision ID: b2c4d6e8f0a1
Revises: 6b9e3f8d2a15, a1c3f5e7b9d2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'b2c4d6e8f0a1'
down_revision = ('6b9e3f8d2a15', 'a1c3f5e7b9d2')
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('credit_card_transactions')}
    if 'vendor_id' not in columns:
        op.add_column(
            'credit_card_transactions',
            sa.Column('vendor_id', sa.Integer(), nullable=True),
        )


def downgrade():
    inspector = inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('credit_card_transactions')}
    if 'vendor_id' in columns:
        op.drop_column('credit_card_transactions', 'vendor_id')