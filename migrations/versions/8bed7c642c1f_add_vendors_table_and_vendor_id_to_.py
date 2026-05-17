"""Add vendors table and vendor_id to transactions

Revision ID: 8bed7c642c1f
Revises: 
Create Date: 2026-01-25 22:36:07.253303

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '8bed7c642c1f'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    # This migration is applied to existing SQLite databases where transactions
    # can include self-referential FKs; avoid batch table recreation to prevent
    # CircularDependencyError during column reordering.
    transaction_columns = {col['name'] for col in inspector.get_columns('transactions')}
    if 'vendor_id' not in transaction_columns:
        op.add_column('transactions', sa.Column('vendor_id', sa.Integer(), nullable=True))

    # SQLite can't add a foreign key constraint via ALTER TABLE; skip it there.
    if conn.dialect.name != 'sqlite':
        fk_names = {fk.get('name') for fk in inspector.get_foreign_keys('transactions') if fk.get('name')}
        if 'fk_transactions_vendor_id' not in fk_names:
            op.create_foreign_key(
                'fk_transactions_vendor_id',
                'transactions',
                'vendors',
                ['vendor_id'],
                ['id'],
            )


def downgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    transaction_columns = {col['name'] for col in inspector.get_columns('transactions')}
    if 'vendor_id' not in transaction_columns:
        return

    if conn.dialect.name != 'sqlite':
        fk_names = {fk.get('name') for fk in inspector.get_foreign_keys('transactions') if fk.get('name')}
        if 'fk_transactions_vendor_id' in fk_names:
            op.drop_constraint('fk_transactions_vendor_id', 'transactions', type_='foreignkey')
        op.drop_column('transactions', 'vendor_id')
    else:
        with op.batch_alter_table('transactions', schema=None) as batch_op:
            batch_op.drop_column('vendor_id')
