"""Widen calculated quantities and rates without changing money precision.

Revision ID: a24c6e8f1032
Revises: f1a3b5c7d9e1
"""
from alembic import op
import sqlalchemy as sa


revision = 'a24c6e8f1032'
down_revision = 'f1a3b5c7d9e1'
branch_labels = None
depends_on = None

CHANGES = (
    ('fuel_records', 'mpg', 6, 2, True),
    ('fuel_records', 'price_per_mile', 6, 2, True),
    ('trips', 'approx_mpg', 6, 2, True),
    ('trips', 'gallons_used', 8, 2, True),
    ('trips', 'cumulative_gallons', 8, 2, True),
    ('loans', 'monthly_apr', 5, 2, False),
    ('mortgage_snapshots', 'interest_rate', 5, 4, True),
    ('pension_snapshots', 'growth_percent', 10, 4, True),
    ('property_valuation_snapshots', 'change_percent', 10, 4, True),
)


def change_types(widen):
    if op.get_bind().dialect.name == 'sqlite':
        # SQLite ignores NUMERIC precision/scale. Keep raw values and FK-linked
        # tables untouched; model result processors apply the new scale on read.
        return
    for table, column, precision, scale, nullable in CHANGES:
        old = sa.Numeric(precision, scale)
        new = sa.Numeric(precision - scale + 8, 8)
        op.alter_column(
            table, column, existing_type=old if widen else new,
            type_=new if widen else old, existing_nullable=nullable,
        )


def upgrade():
    change_types(True)


def downgrade():
    # PostgreSQL narrowing can round values; take a recovery dump before downgrading.
    change_types(False)
