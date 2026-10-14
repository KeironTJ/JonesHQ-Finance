"""add revocable user sessions

Revision ID: d9e1f3a5b7c9
Revises: c8d0e2f4a6b8
Create Date: 2026-10-14 22:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd9e1f3a5b7c9'
down_revision = 'c8d0e2f4a6b8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('remember', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_sessions_user_id_users',
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_sessions_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_user_sessions_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_user_sessions_token_hash'))
    op.drop_table('user_sessions')
