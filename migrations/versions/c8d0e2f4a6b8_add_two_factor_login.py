"""add two-factor login

Revision ID: c8d0e2f4a6b8
Revises: b7c9d1e3f5a7
Create Date: 2026-10-14 22:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8d0e2f4a6b8'
down_revision = 'b7c9d1e3f5a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('totp_secret', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('totp_enabled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('totp_last_step', sa.Integer(), nullable=True))

    op.create_table(
        'user_recovery_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_recovery_codes_user_id_users',
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user_recovery_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_recovery_codes_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_recovery_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_recovery_codes_user_id'))
    op.drop_table('user_recovery_codes')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('totp_last_step')
        batch_op.drop_column('totp_enabled_at')
        batch_op.drop_column('totp_secret')
