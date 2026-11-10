"""add opt-in rewards celebration board

Revision ID: a72d09c4e816
Revises: f6a4c9d2b871
"""
from alembic import op
import sqlalchemy as sa


revision = 'a72d09c4e816'
down_revision = 'f6a4c9d2b871'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('families') as batch:
        batch.add_column(sa.Column(
            'rewards_board_enabled', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))


def downgrade():
    with op.batch_alter_table('families') as batch:
        batch.drop_column('rewards_board_enabled')
