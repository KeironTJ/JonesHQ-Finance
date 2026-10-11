"""add assigned_to to credit card transactions

Revision ID: f8b4d0e63a95
Revises: e7a3c9d52f84
"""
from alembic import op
import sqlalchemy as sa


revision = 'f8b4d0e63a95'
down_revision = 'e7a3c9d52f84'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'credit_card_transactions',
        sa.Column('assigned_to', sa.String(length=100), nullable=True),
    )


def downgrade():
    op.drop_column('credit_card_transactions', 'assigned_to')
