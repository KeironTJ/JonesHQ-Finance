"""add household setup progress

Revision ID: f6a4c9d2b871
Revises: c27d3f9b456a
Create Date: 2026-11-10 21:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f6a4c9d2b871'
down_revision = 'c27d3f9b456a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('families') as batch:
        batch.add_column(sa.Column(
            'setup_progress', sa.JSON(), nullable=False,
            server_default=sa.text("'{}'"),
        ))


def downgrade():
    with op.batch_alter_table('families') as batch:
        batch.drop_column('setup_progress')
