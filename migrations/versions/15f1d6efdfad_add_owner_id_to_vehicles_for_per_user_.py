"""add owner_id to vehicles for per-user privacy

Revision ID: 15f1d6efdfad
Revises: 893d861fa160
Create Date: 2026-09-23 22:41:01.400388

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '15f1d6efdfad'
down_revision = '893d861fa160'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_vehicles_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_vehicles_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('vehicles', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vehicles_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_vehicles_owner_id'))
        batch_op.drop_column('owner_id')