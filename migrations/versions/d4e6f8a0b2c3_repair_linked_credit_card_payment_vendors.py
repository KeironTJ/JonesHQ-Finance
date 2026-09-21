"""repair linked credit card payment vendors

Revision ID: d4e6f8a0b2c3
Revises: c3d5e7f9a1b2
"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e6f8a0b2c3'
down_revision = 'c3d5e7f9a1b2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    payments = sa.table(
        'credit_card_transactions',
        sa.column('id', sa.Integer),
        sa.column('credit_card_id', sa.Integer),
        sa.column('bank_transaction_id', sa.Integer),
        sa.column('transaction_type', sa.String),
        sa.column('vendor_id', sa.Integer),
    )
    bank_transactions = sa.table(
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
    cards = sa.table(
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

    rows = conn.execute(
        sa.select(
            payments.c.id,
            payments.c.credit_card_id,
            payments.c.bank_transaction_id,
        ).where(payments.c.transaction_type == 'Payment')
    ).mappings()

    for row in rows:
        card = conn.execute(
            sa.select(cards.c.family_id, cards.c.card_name).where(
                cards.c.id == row['credit_card_id']
            )
        ).mappings().first()
        if not card:
            continue

        account_name = None
        bank_id = row['bank_transaction_id']
        if bank_id:
            account_id = conn.execute(
                sa.select(bank_transactions.c.account_id).where(
                    bank_transactions.c.id == bank_id
                )
            ).scalar()
            if account_id:
                account_name = conn.execute(
                    sa.select(accounts.c.name).where(accounts.c.id == account_id)
                ).scalar()

        vendor_name = account_name or card['card_name']
        vendor_id = conn.execute(
            sa.select(vendors.c.id).where(
                vendors.c.family_id == card['family_id'],
                vendors.c.name == vendor_name,
            )
        ).scalar()
        if vendor_id is None:
            conn.execute(vendors.insert().values(
                family_id=card['family_id'], name=vendor_name
            ))
            vendor_id = conn.execute(
                sa.select(vendors.c.id).where(
                    vendors.c.family_id == card['family_id'],
                    vendors.c.name == vendor_name,
                )
            ).scalar()

        conn.execute(
            payments.update().where(payments.c.id == row['id']).values(
                vendor_id=vendor_id
            )
        )
        if bank_id:
            conn.execute(
                bank_transactions.update().where(bank_transactions.c.id == bank_id).values(
                    vendor_id=vendor_id
                )
            )


def downgrade():
    pass