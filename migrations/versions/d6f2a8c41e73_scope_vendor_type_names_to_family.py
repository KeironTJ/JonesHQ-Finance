"""scope vendor type names to family

Revision ID: d6f2a8c41e73
Revises: c4a7e2f91b63
Create Date: 2026-09-24 00:10:00.000000

"""
from alembic import op


revision = 'd6f2a8c41e73'
down_revision = 'c4a7e2f91b63'
branch_labels = None
depends_on = None


def upgrade():
    naming_convention = {
        'uq': 'uq_%(table_name)s_%(column_0_name)s',
    }
    with op.batch_alter_table(
        'vendor_types',
        schema=None,
        naming_convention=naming_convention,
    ) as batch_op:
        batch_op.drop_constraint('uq_vendor_types_name', type_='unique')
        batch_op.create_unique_constraint(
            'uq_vendor_types_family_name',
            ['family_id', 'name'],
        )


def downgrade():
    with op.batch_alter_table('vendor_types', schema=None) as batch_op:
        batch_op.drop_constraint('uq_vendor_types_family_name', type_='unique')
        batch_op.create_unique_constraint('uq_vendor_types_name', ['name'])