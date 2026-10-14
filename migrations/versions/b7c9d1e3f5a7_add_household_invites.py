"""add household invites

Revision ID: b7c9d1e3f5a7
Revises: a6b8c0d2e4f6
Create Date: 2026-10-14 21:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7c9d1e3f5a7'
down_revision = 'a6b8c0d2e4f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'household_invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('used_by_id', sa.Integer(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], name='fk_household_invites_created_by_id_users'),
        sa.ForeignKeyConstraint(['used_by_id'], ['users.id'], name='fk_household_invites_used_by_id_users'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('household_invites', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_household_invites_token_hash'), ['token_hash'], unique=True)


def downgrade():
    with op.batch_alter_table('household_invites', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_household_invites_token_hash'))
    op.drop_table('household_invites')
