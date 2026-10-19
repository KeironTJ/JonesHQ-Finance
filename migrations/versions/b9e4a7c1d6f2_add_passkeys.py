"""Add passkey credentials, one-time challenges and session authentication method.

Revision ID: b9e4a7c1d6f2
Revises: a8d3f6b0c4e5
"""
from alembic import op
import sqlalchemy as sa


revision = 'b9e4a7c1d6f2'
down_revision = 'a8d3f6b0c4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_sessions', sa.Column(
        'authentication_method', sa.String(20), nullable=False, server_default='password',
    ))
    op.create_table(
        'user_passkeys',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credential_id', sa.String(1400), nullable=False, unique=True),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_user_passkeys_user_id', 'user_passkeys', ['user_id'])
    op.create_table(
        'passkey_challenges',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('challenge', sa.LargeBinary(), nullable=False),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
    )
    op.create_index('ix_passkey_challenges_user_id', 'passkey_challenges', ['user_id'])
    op.create_index('ix_passkey_challenges_expires_at', 'passkey_challenges', ['expires_at'])


def downgrade():
    op.drop_table('passkey_challenges')
    op.drop_table('user_passkeys')
    with op.batch_alter_table('user_sessions') as batch_op:
        batch_op.drop_column('authentication_method')
