"""add_loan_term_changes_and_weekend_adjustment

Revision ID: aba54c1e02c1
Revises: 3cdb0e53888d
Create Date: 2026-04-27 13:33:27.812363

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision = 'aba54c1e02c1'
down_revision = '3cdb0e53888d'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)
    existing_tables = inspector.get_table_names()

    # Create loan_term_changes table (guard against partial prior run)
    if 'loan_term_changes' not in existing_tables:
        op.create_table(
            'loan_term_changes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('family_id', sa.Integer(), nullable=True),
            sa.Column('loan_id', sa.Integer(), nullable=False),
            sa.Column('effective_date', sa.Date(), nullable=False),
            sa.Column('previous_monthly_payment', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('new_monthly_payment', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('previous_annual_apr', sa.Numeric(precision=5, scale=2), nullable=True),
            sa.Column('new_annual_apr', sa.Numeric(precision=5, scale=2), nullable=True),
            sa.Column('previous_payment_day', sa.Integer(), nullable=True),
            sa.Column('new_payment_day', sa.Integer(), nullable=True),
            sa.Column('previous_term_months', sa.Integer(), nullable=True),
            sa.Column('new_term_months', sa.Integer(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['family_id'], ['families.id'], ),
            sa.ForeignKeyConstraint(['loan_id'], ['loans.id'], ),
            sa.PrimaryKeyConstraint('id'),
        )

    # Add index if not already there
    loans_tc_indexes = [i['name'] for i in inspector.get_indexes('loan_term_changes')] if 'loan_term_changes' in existing_tables else []
    if 'ix_loan_term_changes_family_id' not in loans_tc_indexes:
        with op.batch_alter_table('loan_term_changes', schema=None) as batch_op:
            batch_op.create_index(
                batch_op.f('ix_loan_term_changes_family_id'), ['family_id'], unique=False
            )

    # Add weekend_adjustment column to loans (guard against partial prior run)
    loans_cols = [c['name'] for c in inspector.get_columns('loans')]
    if 'weekend_adjustment' not in loans_cols:
        with op.batch_alter_table('loans', schema=None) as batch_op:
            batch_op.add_column(sa.Column('weekend_adjustment', sa.String(length=10), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = Inspector.from_engine(conn)

    loans_cols = [c['name'] for c in inspector.get_columns('loans')]
    if 'weekend_adjustment' in loans_cols:
        with op.batch_alter_table('loans', schema=None) as batch_op:
            batch_op.drop_column('weekend_adjustment')

    if 'loan_term_changes' in inspector.get_table_names():
        with op.batch_alter_table('loan_term_changes', schema=None) as batch_op:
            batch_op.drop_index(batch_op.f('ix_loan_term_changes_family_id'))
        op.drop_table('loan_term_changes')
