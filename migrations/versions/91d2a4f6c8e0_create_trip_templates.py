"""create saved trip templates

Revision ID: 91d2a4f6c8e0
Revises: d8e2f4a6b0c9
Create Date: 2026-11-02 19:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '91d2a4f6c8e0'
down_revision = 'd8e2f4a6b0c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=True),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('trip_type', sa.String(length=20), nullable=False),
        sa.Column('miles', sa.Integer(), nullable=False),
        sa.Column('journey_description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_trip_templates_family_id', 'trip_templates', ['family_id'])
    op.create_index('ix_trip_templates_vehicle_id', 'trip_templates', ['vehicle_id'])


def downgrade():
    op.drop_index('ix_trip_templates_vehicle_id', table_name='trip_templates')
    op.drop_index('ix_trip_templates_family_id', table_name='trip_templates')
    op.drop_table('trip_templates')
