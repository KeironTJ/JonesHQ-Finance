"""add owner_id to pensions for per-user privacy

Revision ID: 5d8c0dc1e322
Revises: 9d0242ddc986
Create Date: 2026-09-23 22:04:58.643656

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5d8c0dc1e322'
down_revision = '9d0242ddc986'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pensions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_pensions_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_pensions_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('pensions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pensions_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_pensions_owner_id'))
        batch_op.drop_column('owner_id')