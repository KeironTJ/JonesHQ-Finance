"""add dated subscription price changes

Revision ID: c7d9e1a3b5f7
Revises: b9e4a7c1d6f2
Create Date: 2026-10-20 22:03:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d9e1a3b5f7'
down_revision = 'b9e4a7c1d6f2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subscription_price_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            'amount < 0',
            name='ck_subscription_price_changes_expense_amount',
        ),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(
            ['subscription_id'],
            ['subscriptions.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'subscription_id',
            'effective_date',
            name='uq_subscription_price_changes_effective_date',
        ),
    )
    op.create_index(
        op.f('ix_subscription_price_changes_family_id'),
        'subscription_price_changes',
        ['family_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_subscription_price_changes_subscription_id'),
        'subscription_price_changes',
        ['subscription_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f('ix_subscription_price_changes_subscription_id'),
        table_name='subscription_price_changes',
    )
    op.drop_index(
        op.f('ix_subscription_price_changes_family_id'),
        table_name='subscription_price_changes',
    )
    op.drop_table('subscription_price_changes')
