"""Scope settings and tax settings to families.

Revision ID: c9d8e7f6a5b4
Revises: fe5ef92cbed0
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d8e7f6a5b4'
down_revision = 'fe5ef92cbed0'
branch_labels = None
depends_on = None


def _copy_table_without_single_column_unique(table_name, columns, key_column):
    metadata = sa.MetaData()
    inspector = sa.inspect(op.get_bind())
    has_family_id = 'family_id' in {
        column['name'] for column in inspector.get_columns(table_name)
    }
    family_column = sa.Column(
        'family_id', sa.Integer(), sa.ForeignKey('families.id'), nullable=True
    )
    source_columns = columns + [family_column] if has_family_id else columns
    copy_from = sa.Table(table_name, metadata, *source_columns)
    with op.batch_alter_table(table_name, recreate='always', copy_from=copy_from) as batch:
        if not has_family_id:
            batch.add_column(family_column)
        batch.create_index(f'ix_{table_name}_family_id', ['family_id'])
        batch.create_unique_constraint(f'uq_{table_name}_family_key', ['family_id', key_column])


def upgrade():
    settings_columns = [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=500)),
        sa.Column('description', sa.String(length=255)),
        sa.Column('setting_type', sa.String(length=50)),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    ]
    tax_columns = [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tax_year', sa.String(length=9), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('personal_allowance', sa.Numeric(10, 2), nullable=False),
        sa.Column('basic_rate_limit', sa.Numeric(10, 2), nullable=False),
        sa.Column('higher_rate_limit', sa.Numeric(10, 2), nullable=False),
        sa.Column('basic_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('higher_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('additional_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('ni_threshold', sa.Numeric(10, 2), nullable=False),
        sa.Column('ni_upper_earnings', sa.Numeric(10, 2), nullable=False),
        sa.Column('ni_basic_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('ni_additional_rate', sa.Numeric(5, 4), nullable=False),
        sa.Column('is_active', sa.Boolean()),
        sa.Column('notes', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
    ]

    _copy_table_without_single_column_unique('settings', settings_columns, 'key')
    _copy_table_without_single_column_unique('tax_settings', tax_columns, 'tax_year')

    bind = op.get_bind()
    families = [row[0] for row in bind.execute(sa.text('SELECT id FROM families'))]

    if families:
        for family_id in families:
            bind.execute(sa.text(
                'INSERT INTO settings '
                '(family_id, key, value, description, setting_type, created_at, updated_at) '
                'SELECT :family_id, key, value, description, setting_type, created_at, updated_at '
                'FROM settings WHERE family_id IS NULL'
            ), {'family_id': family_id})
            bind.execute(sa.text(
                'INSERT INTO tax_settings '
                '(family_id, tax_year, effective_from, effective_to, personal_allowance, '
                'basic_rate_limit, higher_rate_limit, basic_rate, higher_rate, additional_rate, '
                'ni_threshold, ni_upper_earnings, ni_basic_rate, ni_additional_rate, is_active, '
                'notes, created_at, updated_at) '
                'SELECT :family_id, tax_year, effective_from, effective_to, personal_allowance, '
                'basic_rate_limit, higher_rate_limit, basic_rate, higher_rate, additional_rate, '
                'ni_threshold, ni_upper_earnings, ni_basic_rate, ni_additional_rate, is_active, '
                'notes, created_at, updated_at '
                'FROM tax_settings WHERE family_id IS NULL'
            ), {'family_id': family_id})

        bind.execute(sa.text('DELETE FROM settings WHERE family_id IS NULL'))


def downgrade():
    raise RuntimeError('Downgrading family-scoped settings would discard family-specific values.')
