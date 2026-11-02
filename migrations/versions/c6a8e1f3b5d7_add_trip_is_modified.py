"""flag routine occurrences edited for a single day

Revision ID: c6a8e1f3b5d7
Revises: 4f7b2c9d1e63
Create Date: 2026-11-02 20:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c6a8e1f3b5d7'
down_revision = '4f7b2c9d1e63'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_modified', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))


def downgrade():
    with op.batch_alter_table('trips', schema=None) as batch_op:
        batch_op.drop_column('is_modified')
