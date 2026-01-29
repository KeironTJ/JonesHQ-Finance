"""add_weekly_pattern_to_activity_types

Revision ID: e3896d18dba8
Revises: edb92cc21043
Create Date: 2026-01-29 20:35:18.444984

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3896d18dba8'
down_revision = 'edb92cc21043'
branch_labels = None
depends_on = None


def upgrade():
    # Add weekly pattern columns to child_activity_types
    with op.batch_alter_table('child_activity_types', schema=None) as batch_op:
        batch_op.add_column(sa.Column('occurs_monday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_tuesday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_wednesday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_thursday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_friday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_saturday', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('occurs_sunday', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    # Remove weekly pattern columns from child_activity_types
    with op.batch_alter_table('child_activity_types', schema=None) as batch_op:
        batch_op.drop_column('occurs_sunday')
        batch_op.drop_column('occurs_saturday')
        batch_op.drop_column('occurs_friday')
        batch_op.drop_column('occurs_thursday')
        batch_op.drop_column('occurs_wednesday')
        batch_op.drop_column('occurs_tuesday')
        batch_op.drop_column('occurs_monday')
