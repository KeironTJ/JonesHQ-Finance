"""add default account to users

Revision ID: c4a7e2f91b63
Revises: 16b38de81612
Create Date: 2026-09-23 23:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4a7e2f91b63'
down_revision = '16b38de81612'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_account_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_users_default_account',
            'accounts',
            ['default_account_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_default_account', type_='foreignkey')
        batch_op.drop_column('default_account_id')