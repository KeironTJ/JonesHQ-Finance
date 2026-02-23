"""add is_site_admin to users

Revision ID: 8b97863c529e
Revises: fdd33114b3e8
Create Date: 2026-02-23 12:40:58.509784

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8b97863c529e'
down_revision = 'fdd33114b3e8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_site_admin', sa.Boolean(), nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_site_admin')
