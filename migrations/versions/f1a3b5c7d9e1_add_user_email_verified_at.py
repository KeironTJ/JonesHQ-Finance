"""add user email verification time

Revision ID: f1a3b5c7d9e1
Revises: e0f2a4b6c8d0
Create Date: 2026-10-14 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a3b5c7d9e1'
down_revision = 'e0f2a4b6c8d0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('email_verified_at')
