"""Add is_fixed field to credit_card_transactions

Revision ID: 0c3b44686205
Revises: 8bed7c642c1f
Create Date: 2026-01-28 07:40:44.004292

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '0c3b44686205'
down_revision = '8bed7c642c1f'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_fixed column to credit_card_transactions if missing.
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('credit_card_transactions')}
    if 'is_fixed' not in columns:
        op.add_column(
            'credit_card_transactions',
            sa.Column('is_fixed', sa.Boolean(), nullable=True, server_default='0')
        )


def downgrade():
    # Remove is_fixed column if present.
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('credit_card_transactions')}
    if 'is_fixed' in columns:
        if conn.dialect.name == 'sqlite':
            with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
                batch_op.drop_column('is_fixed')
        else:
            op.drop_column('credit_card_transactions', 'is_fixed')
