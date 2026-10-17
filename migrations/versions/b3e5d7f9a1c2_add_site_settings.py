"""Add site_settings for operator-managed service switches.

Revision ID: b3e5d7f9a1c2
Revises: a24c6e8f1032
"""
from alembic import op
import sqlalchemy as sa


revision = 'b3e5d7f9a1c2'
down_revision = 'a24c6e8f1032'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'site_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('household_signups_paused', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('signups_paused_message', sa.String(length=300), nullable=True),
        sa.Column('announcement', sa.String(length=500), nullable=True),
        sa.Column('announcement_level', sa.String(length=10), nullable=False, server_default='info'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('site_settings')
