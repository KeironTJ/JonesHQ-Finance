"""add_transaction_day_to_children

Revision ID: 37b762477f3b
Revises: 03551550f90a
Create Date: 2026-01-29 22:09:56.852322

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '37b762477f3b'
down_revision = '03551550f90a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.add_column(sa.Column('transaction_day', sa.Integer(), nullable=False, server_default='28'))


def downgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.drop_column('transaction_day')
