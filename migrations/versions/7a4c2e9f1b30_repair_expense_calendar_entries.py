"""repair expense calendar entries

Revision ID: 7a4c2e9f1b30
Revises: d0e1f2a3b4c5
Create Date: 2026-09-19 00:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7a4c2e9f1b30'
down_revision = 'd0e1f2a3b4c5'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'expense_calendar_entries' not in inspector.get_table_names():
        op.create_table(
            'expense_calendar_entries',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=True),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('assigned_to', sa.String(length=100), nullable=True),
            sa.Column('expense_id', sa.Integer(), sa.ForeignKey('expenses.id'), nullable=True),
            sa.Column('amount', sa.Numeric(10, 2), nullable=True),
            sa.Column('description', sa.String(length=255), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index(
            'ix_expense_calendar_entries_family_id',
            'expense_calendar_entries',
            ['family_id'],
        )
        return

    columns = {column['name'] for column in inspector.get_columns('expense_calendar_entries')}
    if 'family_id' not in columns:
        with op.batch_alter_table('expense_calendar_entries') as batch_op:
            batch_op.add_column(sa.Column('family_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_expense_calendar_entries_family_id',
                'families',
                ['family_id'],
                ['id'],
            )

    indexes = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes('expense_calendar_entries')}
    if 'ix_expense_calendar_entries_family_id' not in indexes:
        op.create_index(
            'ix_expense_calendar_entries_family_id',
            'expense_calendar_entries',
            ['family_id'],
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'expense_calendar_entries' not in inspector.get_table_names():
        return

    indexes = {index['name'] for index in inspector.get_indexes('expense_calendar_entries')}
    if 'ix_expense_calendar_entries_family_id' in indexes:
        op.drop_index('ix_expense_calendar_entries_family_id', table_name='expense_calendar_entries')

    columns = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('expense_calendar_entries')}
    if 'family_id' in columns:
        with op.batch_alter_table('expense_calendar_entries') as batch_op:
            batch_op.drop_column('family_id')