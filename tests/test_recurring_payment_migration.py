from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


def test_recurring_payment_rename_migration_preserves_data_and_foreign_keys():
    engine = sa.create_engine('sqlite://')
    metadata = sa.MetaData()
    families = sa.Table('families', metadata, sa.Column('id', sa.Integer, primary_key=True))
    accounts = sa.Table('accounts', metadata, sa.Column('id', sa.Integer, primary_key=True))
    cards = sa.Table('credit_cards', metadata, sa.Column('id', sa.Integer, primary_key=True))
    categories = sa.Table('categories', metadata, sa.Column('id', sa.Integer, primary_key=True))
    vendors = sa.Table('vendors', metadata, sa.Column('id', sa.Integer, primary_key=True))
    subscriptions = sa.Table(
        'subscriptions',
        metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('family_id', sa.Integer, sa.ForeignKey('families.id'), nullable=False),
        sa.Column('account_id', sa.Integer, sa.ForeignKey('accounts.id')),
        sa.Column('credit_card_id', sa.Integer, sa.ForeignKey('credit_cards.id')),
        sa.Column('category_id', sa.Integer, sa.ForeignKey('categories.id')),
        sa.Column('vendor_id', sa.Integer, sa.ForeignKey('vendors.id')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('frequency', sa.String(20), nullable=False),
        sa.Column('start_date', sa.Date, nullable=False),
        sa.Column('horizon_years', sa.Integer, nullable=False),
        sa.Column('is_active', sa.Boolean, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('weekend_adjustment', sa.String(10), nullable=False),
        sa.CheckConstraint('amount < 0', name='ck_subscriptions_expense_amount'),
    )
    changes = sa.Table(
        'subscription_price_changes',
        metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('family_id', sa.Integer, sa.ForeignKey('families.id'), nullable=False),
        sa.Column(
            'subscription_id',
            sa.Integer,
            sa.ForeignKey('subscriptions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('effective_date', sa.Date, nullable=False),
        sa.Column('note', sa.String(255)),
        sa.CheckConstraint(
            'amount < 0', name='ck_subscription_price_changes_expense_amount'
        ),
        sa.UniqueConstraint(
            'subscription_id',
            'effective_date',
            name='uq_subscription_price_changes_effective_date',
        ),
    )
    transactions = sa.Table(
        'transactions',
        metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column(
            'subscription_id',
            sa.Integer,
            sa.ForeignKey('subscriptions.id', ondelete='SET NULL'),
        ),
    )
    card_transactions = sa.Table(
        'credit_card_transactions',
        metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column(
            'subscription_id',
            sa.Integer,
            sa.ForeignKey('subscriptions.id', ondelete='SET NULL'),
        ),
    )
    metadata.create_all(engine)

    indexes = (
        ('subscriptions', 'ix_subscriptions_family_id', ['family_id']),
        ('subscription_price_changes', 'ix_subscription_price_changes_family_id', ['family_id']),
        (
            'subscription_price_changes',
            'ix_subscription_price_changes_subscription_id',
            ['subscription_id'],
        ),
        ('transactions', 'ix_transactions_subscription_id', ['subscription_id']),
        (
            'credit_card_transactions',
            'ix_credit_card_transactions_subscription_id',
            ['subscription_id'],
        ),
    )
    with engine.begin() as connection:
        for table, name, columns in indexes:
            connection.execute(sa.text(
                f'CREATE INDEX {name} ON {table} ({", ".join(columns)})'
            ))
        connection.execute(sa.text('INSERT INTO families (id) VALUES (1)'))
        connection.execute(sa.text('INSERT INTO accounts (id) VALUES (2)'))
        connection.execute(sa.text(
            "INSERT INTO subscriptions "
            "(id, family_id, account_id, name, amount, frequency, start_date, "
            "horizon_years, is_active, weekend_adjustment) "
            "VALUES (3, 1, 2, 'Power', -45, 'monthly', '2026-01-01', 1, 1, 'none')"
        ))
        connection.execute(sa.text(
            "INSERT INTO subscription_price_changes "
            "(id, family_id, subscription_id, amount, effective_date, note) "
            "VALUES (4, 1, 3, -50, '2026-02-01', 'Price update')"
        ))
        connection.execute(sa.text(
            'INSERT INTO transactions (id, subscription_id) VALUES (5, 3)'
        ))
        connection.execute(sa.text(
            'INSERT INTO credit_card_transactions (id, subscription_id) VALUES (6, 3)'
        ))
        migration = import_module(
            'migrations.versions.a7c13d8e5f20_rename_subscriptions_to_recurring_payments'
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        inspector = sa.inspect(connection)
        assert 'recurring_payments' in inspector.get_table_names()
        assert 'recurring_payment_price_changes' in inspector.get_table_names()
        assert 'subscriptions' not in inspector.get_table_names()
        assert 'subscription_price_changes' not in inspector.get_table_names()
        assert 'recurring_payment_id' in {
            column['name'] for column in inspector.get_columns('transactions')
        }
        assert 'recurring_payment_id' in {
            column['name']
            for column in inspector.get_columns('credit_card_transactions')
        }
        assert connection.scalar(sa.text(
            'SELECT name FROM recurring_payments WHERE id = 3'
        )) == 'Power'
        assert connection.scalar(sa.text(
            'SELECT recurring_payment_id FROM recurring_payment_price_changes WHERE id = 4'
        )) == 3
        assert connection.scalar(sa.text(
            'SELECT recurring_payment_id FROM transactions WHERE id = 5'
        )) == 3
        assert connection.scalar(sa.text(
            'SELECT recurring_payment_id FROM credit_card_transactions WHERE id = 6'
        )) == 3
        assert {
            fk['referred_table']
            for fk in inspector.get_foreign_keys('recurring_payment_price_changes')
        } >= {'recurring_payments'}
        assert {
            fk['referred_table'] for fk in inspector.get_foreign_keys('transactions')
        } >= {'recurring_payments'}

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        inspector = sa.inspect(connection)
        assert 'subscriptions' in inspector.get_table_names()
        assert 'subscription_price_changes' in inspector.get_table_names()
        assert connection.scalar(sa.text(
            'SELECT name FROM subscriptions WHERE id = 3'
        )) == 'Power'
        assert connection.scalar(sa.text(
            'SELECT subscription_id FROM subscription_price_changes WHERE id = 4'
        )) == 3
        assert connection.scalar(sa.text(
            'SELECT subscription_id FROM transactions WHERE id = 5'
        )) == 3
