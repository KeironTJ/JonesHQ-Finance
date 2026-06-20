"""Add indexes to trips and fuel_records for vehicle_id, date, and composite

Revision ID: e8f9a2b3c4d5
Revises: b7f94b7f9e11
Create Date: 2026-06-20 00:00:00.000000

"""
from alembic import op

revision = 'e8f9a2b3c4d5'
down_revision = 'b7f94b7f9e11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.create_index('ix_trips_vehicle_id', ['vehicle_id'])
        batch_op.create_index('ix_trips_date', ['date'])
        batch_op.create_index('ix_trips_vehicle_id_date', ['vehicle_id', 'date'])

    with op.batch_alter_table('fuel_records', schema=None) as batch_op:
        batch_op.create_index('ix_fuel_records_vehicle_id', ['vehicle_id'])
        batch_op.create_index('ix_fuel_records_date', ['date'])
        batch_op.create_index('ix_fuel_records_vehicle_id_date', ['vehicle_id', 'date'])


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_index('ix_trips_vehicle_id_date')
        batch_op.drop_index('ix_trips_date')
        batch_op.drop_index('ix_trips_vehicle_id')

    with op.batch_alter_table('fuel_records', schema=None) as batch_op:
        batch_op.drop_index('ix_fuel_records_vehicle_id_date')
        batch_op.drop_index('ix_fuel_records_date')
        batch_op.drop_index('ix_fuel_records_vehicle_id')
