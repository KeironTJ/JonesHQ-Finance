"""Add refuel_threshold_pct to vehicles

Revision ID: a1f3c9e2d047
Revises: 13bd6ec7f3ba
Create Date: 2026-02-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f3c9e2d047'
down_revision = 'fe5ef92cbed0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('refuel_threshold_pct', sa.Numeric(4, 1), nullable=True, server_default='95.0'))


def downgrade():
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.drop_column('refuel_threshold_pct')
