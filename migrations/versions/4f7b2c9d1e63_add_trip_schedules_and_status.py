"""add trip schedules and planned occurrence status

Revision ID: 4f7b2c9d1e63
Revises: 91d2a4f6c8e0
Create Date: 2026-11-02 19:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '4f7b2c9d1e63'
down_revision = '91d2a4f6c8e0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('trip_type', sa.String(length=20), nullable=False),
        sa.Column('miles', sa.Integer(), nullable=False),
        sa.Column('journey_description', sa.String(length=255), nullable=True),
        sa.Column('weekdays', sa.String(length=13), nullable=False),
        sa.Column('frequency', sa.String(length=20), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_schedules_family_id', 'trip_schedules', ['family_id'])
    op.create_index('ix_trip_schedules_vehicle_id', 'trip_schedules', ['vehicle_id'])

    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schedule_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('scheduled_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column(
            'trip_status', sa.String(length=20), nullable=False, server_default='actual',
        ))
        batch_op.create_foreign_key(
            'fk_trips_schedule_id_trip_schedules',
            'trip_schedules',
            ['schedule_id'],
            ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_index('ix_trips_schedule_id', ['schedule_id'])
        batch_op.create_index('ix_trips_trip_status', ['trip_status'])
        batch_op.create_unique_constraint(
            'uq_trips_schedule_scheduled_date',
            ['schedule_id', 'scheduled_date'],
        )


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_constraint('uq_trips_schedule_scheduled_date', type_='unique')
        batch_op.drop_index('ix_trips_trip_status')
        batch_op.drop_index('ix_trips_schedule_id')
        batch_op.drop_constraint('fk_trips_schedule_id_trip_schedules', type_='foreignkey')
        batch_op.drop_column('trip_status')
        batch_op.drop_column('scheduled_date')
        batch_op.drop_column('schedule_id')

    op.drop_index('ix_trip_schedules_vehicle_id', table_name='trip_schedules')
    op.drop_index('ix_trip_schedules_family_id', table_name='trip_schedules')
    op.drop_table('trip_schedules')
