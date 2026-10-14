"""add security events and session reauthentication time

Revision ID: e0f2a4b6c8d0
Revises: d9e1f3a5b7c9
Create Date: 2026-10-14 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e0f2a4b6c8d0'
down_revision = 'd9e1f3a5b7c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reauthenticated_at', sa.DateTime(), nullable=True))

    op.create_table(
        'security_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('family_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('details', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_security_events_user_id_users',
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['family_id'], ['families.id'], name='fk_security_events_family_id_families',
                                ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('security_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_security_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_family_id'), ['family_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_created_at'), ['created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('security_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_security_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_security_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_security_events_family_id'))
        batch_op.drop_index(batch_op.f('ix_security_events_user_id'))
    op.drop_table('security_events')

    with op.batch_alter_table('user_sessions', schema=None) as batch_op:
        batch_op.drop_column('reauthenticated_at')
