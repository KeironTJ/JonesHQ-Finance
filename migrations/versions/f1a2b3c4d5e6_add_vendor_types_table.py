"""add_vendor_types_table

Revision ID: f1a2b3c4d5e6
Revises: 03551550f90a
Create Date: 2026-02-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = '03551550f90a'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)

    if not inspector.has_table('vendor_types'):
        op.create_table(
            'vendor_types',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('name', sa.String(length=50), nullable=False, unique=True),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('sort_order', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    vendors_columns = {col['name'] for col in inspector.get_columns('vendors')}
    if 'vendor_type_id' not in vendors_columns:
        # Clean up any leftover temp tables from previous failed migrations
        if inspector.has_table('_alembic_tmp_vendors'):
            conn.execute(sa.text('DROP TABLE _alembic_tmp_vendors'))
        
        with op.batch_alter_table('vendors', schema=None) as batch_op:
            batch_op.add_column(sa.Column('vendor_type_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_vendors_vendor_type_id', 'vendor_types', ['vendor_type_id'], ['id'])

    vendors_table = sa.table(
        'vendors',
        sa.column('id', sa.Integer),
        sa.column('vendor_type', sa.String),
        sa.column('vendor_type_id', sa.Integer),
    )
    vendor_types_table = sa.table(
        'vendor_types',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('is_active', sa.Boolean),
        sa.column('sort_order', sa.Integer),
        sa.column('created_at', sa.DateTime),
        sa.column('updated_at', sa.DateTime),
    )

    distinct_types = [
        row[0]
        for row in conn.execute(
            sa.select(sa.distinct(vendors_table.c.vendor_type)).where(
                vendors_table.c.vendor_type.isnot(None)
            )
        )
        if row[0]
    ]

    existing_type_names = {
        row[0]
        for row in conn.execute(sa.select(vendor_types_table.c.name))
        if row[0]
    }

    type_id_by_name = {}
    insert_index = len(existing_type_names)
    for name in distinct_types:
        if name in existing_type_names:
            continue
        insert_index += 1
        conn.execute(
            vendor_types_table.insert().values(
                name=name,
                is_active=True,
                sort_order=insert_index,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        row = conn.execute(
            sa.select(vendor_types_table.c.id).where(vendor_types_table.c.name == name)
        ).first()
        if row:
            type_id_by_name[name] = row[0]

    for name in existing_type_names:
        row = conn.execute(
            sa.select(vendor_types_table.c.id).where(vendor_types_table.c.name == name)
        ).first()
        if row:
            type_id_by_name[name] = row[0]

    for name, type_id in type_id_by_name.items():
        conn.execute(
            vendors_table.update()
            .where(vendors_table.c.vendor_type == name)
            .where(vendors_table.c.vendor_type_id.is_(None))
            .values(vendor_type_id=type_id)
        )


def downgrade():
    with op.batch_alter_table('vendors', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vendors_vendor_type_id', type_='foreignkey')
        batch_op.drop_column('vendor_type_id')

    op.drop_table('vendor_types')
