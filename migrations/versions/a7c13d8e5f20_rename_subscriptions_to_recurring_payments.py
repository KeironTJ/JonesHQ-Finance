"""Rename managed subscriptions to recurring payments.

Revision ID: a7c13d8e5f20
Revises: c94f21e60838
"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c13d8e5f20'
down_revision = 'c94f21e60838'
branch_labels = None
depends_on = None


def _rename_index(table, old_name, new_name, columns):
    op.drop_index(old_name, table_name=table)
    op.create_index(new_name, table, columns, unique=False)


def upgrade():
    op.rename_table('subscriptions', 'recurring_payments')
    op.rename_table(
        'subscription_price_changes', 'recurring_payment_price_changes'
    )

    for table in ('transactions', 'credit_card_transactions'):
        op.alter_column(
            table,
            'subscription_id',
            new_column_name='recurring_payment_id',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
    op.alter_column(
        'recurring_payment_price_changes',
        'subscription_id',
        new_column_name='recurring_payment_id',
        existing_type=sa.Integer(),
        existing_nullable=False,
    )

    _rename_index(
        'recurring_payments',
        'ix_subscriptions_family_id',
        'ix_recurring_payments_family_id',
        ['family_id'],
    )
    _rename_index(
        'recurring_payment_price_changes',
        'ix_subscription_price_changes_family_id',
        'ix_recurring_payment_price_changes_family_id',
        ['family_id'],
    )
    _rename_index(
        'recurring_payment_price_changes',
        'ix_subscription_price_changes_subscription_id',
        'ix_recurring_payment_price_changes_recurring_payment_id',
        ['recurring_payment_id'],
    )
    _rename_index(
        'transactions',
        'ix_transactions_subscription_id',
        'ix_transactions_recurring_payment_id',
        ['recurring_payment_id'],
    )
    _rename_index(
        'credit_card_transactions',
        'ix_credit_card_transactions_subscription_id',
        'ix_credit_card_transactions_recurring_payment_id',
        ['recurring_payment_id'],
    )


def downgrade():
    for table, old_name, new_name, columns in (
        (
            'credit_card_transactions',
            'ix_credit_card_transactions_recurring_payment_id',
            'ix_credit_card_transactions_subscription_id',
            ['recurring_payment_id'],
        ),
        (
            'transactions',
            'ix_transactions_recurring_payment_id',
            'ix_transactions_subscription_id',
            ['recurring_payment_id'],
        ),
        (
            'recurring_payment_price_changes',
            'ix_recurring_payment_price_changes_recurring_payment_id',
            'ix_subscription_price_changes_subscription_id',
            ['recurring_payment_id'],
        ),
        (
            'recurring_payment_price_changes',
            'ix_recurring_payment_price_changes_family_id',
            'ix_subscription_price_changes_family_id',
            ['family_id'],
        ),
        (
            'recurring_payments',
            'ix_recurring_payments_family_id',
            'ix_subscriptions_family_id',
            ['family_id'],
        ),
    ):
        _rename_index(table, old_name, new_name, columns)

    for table in ('transactions', 'credit_card_transactions'):
        op.alter_column(
            table,
            'recurring_payment_id',
            new_column_name='subscription_id',
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
    op.alter_column(
        'recurring_payment_price_changes',
        'recurring_payment_id',
        new_column_name='subscription_id',
        existing_type=sa.Integer(),
        existing_nullable=False,
    )

    op.rename_table(
        'recurring_payment_price_changes', 'subscription_price_changes'
    )
    op.rename_table('recurring_payments', 'subscriptions')
