"""Add household module access and managed child accounts.

Revision ID: c81d4e6f9a20
Revises: f42b7a91c6d3
"""
from alembic import op
import sqlalchemy as sa


revision = 'c81d4e6f9a20'
down_revision = 'f42b7a91c6d3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column(
            'account_type', sa.String(length=10), nullable=False, server_default='adult',
        ))
        batch.add_column(sa.Column('guardian_id', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_users_guardian_id_users', 'users', ['guardian_id'], ['id'], ondelete='RESTRICT',
        )
    with op.batch_alter_table('household_memberships') as batch:
        batch.add_column(sa.Column(
            'allowed_modules', sa.JSON(), nullable=False,
            server_default='["finance", "household"]',
        ))


def downgrade():
    with op.batch_alter_table('household_memberships') as batch:
        batch.drop_column('allowed_modules')
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('fk_users_guardian_id_users', type_='foreignkey')
        batch.drop_column('guardian_id')
        batch.drop_column('account_type')
