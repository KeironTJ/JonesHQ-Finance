"""add managed subscriptions

Revision ID: a6b8c0d2e4f6
Revises: f8b4d0e63a95
Create Date: 2026-10-12 21:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a6b8c0d2e4f6'
down_revision = 'f8b4d0e63a95'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('family_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('frequency', sa.String(length=20), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('horizon_years', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=True),
        sa.Column('credit_card_id', sa.Integer(), nullable=True),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('vendor_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint('amount < 0', name='ck_subscriptions_expense_amount'),
        sa.CheckConstraint(
            'horizon_years >= 1 AND horizon_years <= 5',
            name='ck_subscriptions_horizon_years',
        ),
        sa.CheckConstraint(
            '(account_id IS NOT NULL AND credit_card_id IS NULL) OR '
            '(account_id IS NULL AND credit_card_id IS NOT NULL)',
            name='ck_subscriptions_single_target',
        ),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['credit_card_id'], ['credit_cards.id']),
        sa.ForeignKeyConstraint(['family_id'], ['families.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_subscriptions_family_id'), 'subscriptions', ['family_id'], unique=False
    )
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subscription_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            op.f('ix_transactions_subscription_id'), ['subscription_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_transactions_subscription_id_subscriptions',
            'subscriptions',
            ['subscription_id'],
            ['id'],
            ondelete='SET NULL',
        )

    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('subscription_id', sa.Integer(), nullable=True))
        batch_op.create_index(
            op.f('ix_credit_card_transactions_subscription_id'),
            ['subscription_id'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_credit_card_transactions_subscription_id_subscriptions',
            'subscriptions',
            ['subscription_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('credit_card_transactions', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_credit_card_transactions_subscription_id_subscriptions',
            type_='foreignkey',
        )
        batch_op.drop_index(
            op.f('ix_credit_card_transactions_subscription_id')
        )
        batch_op.drop_column('subscription_id')

    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_transactions_subscription_id_subscriptions', type_='foreignkey'
        )
        batch_op.drop_index(op.f('ix_transactions_subscription_id'))
        batch_op.drop_column('subscription_id')

    op.drop_index(op.f('ix_subscriptions_family_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
