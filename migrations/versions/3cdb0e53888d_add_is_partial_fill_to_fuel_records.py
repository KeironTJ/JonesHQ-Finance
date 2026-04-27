"""add_is_partial_fill_to_fuel_records

Revision ID: 3cdb0e53888d
Revises: c01178bbb3c4
Create Date: 2026-04-27 11:31:05.141806

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3cdb0e53888d'
down_revision = 'c01178bbb3c4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fuel_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'is_partial_fill',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false()
        ))


def downgrade():
    with op.batch_alter_table('fuel_records', schema=None) as batch_op:
        batch_op.drop_column('is_partial_fill')
