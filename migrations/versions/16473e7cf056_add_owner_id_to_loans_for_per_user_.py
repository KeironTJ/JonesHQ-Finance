"""add owner_id to loans for per-user privacy

Revision ID: 16473e7cf056
Revises: 5d8c0dc1e322
Create Date: 2026-09-23 22:22:03.684248

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16473e7cf056'
down_revision = '5d8c0dc1e322'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('loans', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_loans_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_loans_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('loans', schema=None) as batch_op:
        batch_op.drop_constraint('fk_loans_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_loans_owner_id'))
        batch_op.drop_column('owner_id')