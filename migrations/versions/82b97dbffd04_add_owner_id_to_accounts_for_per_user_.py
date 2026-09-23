"""add owner_id to accounts for per-user privacy

Revision ID: 82b97dbffd04
Revises: e5f7a9b1c3d4
Create Date: 2026-09-23 21:49:37.751889

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '82b97dbffd04'
down_revision = 'e5f7a9b1c3d4'
branch_labels = None
depends_on = None


def upgrade():
    # Add owner_id column to accounts table (NULL = shared with the family)
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_accounts_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key('fk_accounts_owner', 'users', ['owner_id'], ['id'])


def downgrade():
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_accounts_owner', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_accounts_owner_id'))
        batch_op.drop_column('owner_id')
