"""add_default_account_to_children

Revision ID: 03551550f90a
Revises: e3896d18dba8
Create Date: 2026-01-29 21:31:01.458269

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '03551550f90a'
down_revision = 'e3896d18dba8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_children_default_account', 'accounts', ['default_account_id'], ['id'])


def downgrade():
    with op.batch_alter_table('children', schema=None) as batch_op:
        batch_op.drop_constraint('fk_children_default_account', type_='foreignkey')
        batch_op.drop_column('default_account_id')
