"""backfill credit card payment vendors

Revision ID: c3d5e7f9a1b2
Revises: b2c4d6e8f0a1
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d5e7f9a1b2'
down_revision = 'b2c4d6e8f0a1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    credit_card_transactions = sa.table(
        'credit_card_transactions',
        sa.column('id', sa.Integer),
        sa.column('family_id', sa.Integer),
        sa.column('credit_card_id', sa.Integer),
        sa.column('bank_transaction_id', sa.Integer),
        sa.column('transaction_type', sa.String),
        sa.column('vendor_id', sa.Integer),
    )
    transactions = sa.table(
        'transactions',
        sa.column('id', sa.Integer),
        sa.column('account_id', sa.Integer),
        sa.column('vendor_id', sa.Integer),
    )
    accounts = sa.table(
        'accounts',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
    )
    credit_cards = sa.table(
        'credit_cards',
        sa.column('id', sa.Integer),
        sa.column('family_id', sa.Integer),
        sa.column('card_name', sa.String),
    )
    vendors = sa.table(
        'vendors',
        sa.column('id', sa.Integer),
        sa.column('family_id', sa.Integer),
        sa.column('name', sa.String),
    )

    payment_rows = conn.execute(
        sa.select(
            credit_card_transactions.c.id,
            credit_card_transactions.c.family_id,
            credit_card_transactions.c.credit_card_id,
            credit_card_transactions.c.bank_transaction_id,
        ).where(credit_card_transactions.c.transaction_type == 'Payment')
    ).mappings()

    for payment in payment_rows:
        card = conn.execute(
            sa.select(credit_cards.c.family_id, credit_cards.c.card_name).where(
                credit_cards.c.id == payment['credit_card_id']
            )
        ).mappings().first()
        if not card:
            continue

        account_name = None
        bank_transaction_id = payment['bank_transaction_id']
        if bank_transaction_id:
            bank_transaction = conn.execute(
                sa.select(transactions.c.account_id).where(
                    transactions.c.id == bank_transaction_id
                )
            ).first()
            if bank_transaction and bank_transaction.account_id:
                account_name = conn.execute(
                    sa.select(accounts.c.name).where(
                        accounts.c.id == bank_transaction.account_id
                    )
                ).scalar()

        vendor_name = account_name or card.card_name
        family_id = payment['family_id'] or card['family_id']
        vendor_id = conn.execute(
            sa.select(vendors.c.id).where(
                vendors.c.family_id == family_id,
                vendors.c.name == vendor_name,
            )
        ).scalar()
        if vendor_id is None:
            conn.execute(
                vendors.insert().values(family_id=family_id, name=vendor_name)
            )
            vendor_id = conn.execute(
                sa.select(vendors.c.id).where(
                    vendors.c.family_id == family_id,
                    vendors.c.name == vendor_name,
                )
            ).scalar()

        conn.execute(
            credit_card_transactions.update().where(
                credit_card_transactions.c.id == payment['id']
            ).values(vendor_id=vendor_id)
        )
        if bank_transaction_id:
            conn.execute(
                transactions.update().where(
                    transactions.c.id == bank_transaction_id
                ).values(vendor_id=vendor_id)
            )


def downgrade():
    pass