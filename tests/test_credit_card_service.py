"""
Integration tests for CreditCardService.

These tests create real database objects (in-memory SQLite) and call the
service methods, asserting on the resulting transactions and balances.

get_family_id() is patched via monkeypatch so that family_query() works
without an active HTTP request / logged-in user.
"""
from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.categories import Category
from models.accounts import Account
from models.transactions import Transaction
from models.expenses import Expense
from models.family import Family
from services.finance.credit_card_service import CreditCardService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def family_id(app):
    f = Family(name='CC Test Family')
    db.session.add(f)
    db.session.commit()
    return f.id


@pytest.fixture
def card(app, family_id):
    c = CreditCard(
        family_id=family_id,
        card_name='Test Card',
        annual_apr=Decimal('24.0'),
        monthly_apr=Decimal('2.0'),
        credit_limit=Decimal('5000.00'),
        current_balance=Decimal('0.00'),
        min_payment_percent=Decimal('2.0'),
        set_payment=Decimal('200.00'),
        statement_date=15,
        is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


@pytest.fixture(autouse=False)
def patch_family(monkeypatch, family_id):
    """Make family_query() return records for our test family."""
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family_id)


def _add_purchase(card, amount, txn_date, family_id):
    """Insert a credit card purchase and recalculate the card balance."""
    cat = Category(
        family_id=family_id,
        name='Test Purchase',
        head_budget='Test',
        sub_budget='Purchase',
        category_type='expense',
    )
    db.session.add(cat)
    db.session.flush()

    txn = CreditCardTransaction(
        family_id=family_id,
        credit_card_id=card.id,
        category_id=cat.id,
        date=txn_date,
        day_name=txn_date.strftime('%A'),
        week=f"{txn_date.isocalendar()[1]:02d}-{txn_date.year}",
        month=txn_date.strftime('%Y-%m'),
        head_budget='Test',
        sub_budget='Purchase',
        item='Test purchase',
        transaction_type='Purchase',
        amount=amount,
        is_paid=False,
        is_fixed=False,
    )
    db.session.add(txn)
    db.session.commit()
    CreditCardTransaction.recalculate_card_balance(card.id)
    db.session.refresh(card)
    return txn


# ---------------------------------------------------------------------------
# CreditCardService.calculate_interest
# ---------------------------------------------------------------------------

class TestCalculateInterest:
    def test_calculates_monthly_interest_correctly(self, app, card, patch_family):
        # 2% monthly on £1000 debt = £20
        result = CreditCardService.calculate_interest(
            card.id, date(2026, 2, 15), balance_to_use=-1000.0
        )
        assert result == pytest.approx(20.0)

    def test_returns_zero_during_zero_percent_promo(self, app, card, patch_family):
        card.purchase_0_percent_until = date(2026, 12, 31)
        db.session.commit()
        result = CreditCardService.calculate_interest(
            card.id, date(2026, 6, 15), balance_to_use=-1000.0
        )
        assert result == 0.0

    def test_returns_zero_for_zero_balance(self, app, card, patch_family):
        result = CreditCardService.calculate_interest(
            card.id, date(2026, 2, 15), balance_to_use=0.0
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# CreditCardService.generate_monthly_statement
# ---------------------------------------------------------------------------

class TestGenerateMonthlyStatement:
    def test_creates_interest_and_payment_when_balance_owed(
        self, app, card, family_id, patch_family
    ):
        _add_purchase(card, Decimal('-500.00'), date(2026, 2, 1), family_id)

        result = CreditCardService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is not None, "Expected an interest transaction"
        assert result['payment_txn'] is not None, "Expected a payment transaction"
        # 2% of £500 = £10 interest (stored as negative — increases debt)
        assert float(result['interest_txn'].amount) == pytest.approx(-10.0)
        # Payment = min(set_payment=£200, balance=£510) = £200
        assert float(result['payment_txn'].amount) == pytest.approx(200.0)

    def test_zero_interest_statement_created_during_promo(
        self, app, card, family_id, patch_family
    ):
        """A statement transaction IS created during a 0% promo — it records the statement
        period — but the amount should be £0 and marked as promotional rate."""
        card.purchase_0_percent_until = date(2026, 12, 31)
        db.session.commit()
        _add_purchase(card, Decimal('-500.00'), date(2026, 2, 1), family_id)

        result = CreditCardService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is not None, \
            "A statement transaction should still be created during 0% period"
        assert float(result['interest_txn'].amount) == 0.0, \
            "Interest amount must be £0 during 0% promotional period"
        assert result['interest_txn'].is_promotional_rate is True, \
            "Transaction should be flagged as promotional rate"

    def test_no_payment_when_card_has_zero_balance(self, app, card, patch_family):
        result = CreditCardService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is None
        assert result['payment_txn'] is None
        assert result['statement_balance'] == 0

    def test_payment_capped_at_outstanding_balance(
        self, app, card, family_id, patch_family
    ):
        # Debt is only £50 — set_payment is £200, so payment should be capped at £50
        _add_purchase(card, Decimal('-50.00'), date(2026, 2, 1), family_id)

        result = CreditCardService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['payment_txn'] is not None
        assert float(result['payment_txn'].amount) <= 51.0  # at most balance + interest


def test_toggle_transaction_fixed_updates_service_owned_state(
    app, card, family_id, patch_family
):
    transaction = _add_purchase(card, Decimal('-50.00'), date(2026, 2, 1), family_id)

    updated = CreditCardService.toggle_transaction_fixed(transaction.id)

    assert updated.is_fixed is True
    db.session.refresh(transaction)
    assert transaction.is_fixed is True


def test_create_recurring_credit_card_transactions(app, card, family_id, patch_family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family_id)
    category = Category(
        family_id=family_id,
        name='Purchase',
        head_budget='Work',
        sub_budget='Travel',
        category_type='expense',
    )
    db.session.add(category)
    db.session.commit()

    transactions = CreditCardService.create_transactions(card.id, {
        'txn_date': '2026-01-15',
        'txn_type': 'Purchase',
        'txn_item': 'Travel',
        'txn_amount': '-25.00',
        'category_id': str(category.id),
        'txn_fixed': '0',
        'txn_paid': '0',
        'is_recurring': 'on',
        'frequency': 'monthly',
        'occurrences': '2',
        'account_id': '',
    })

    assert len(transactions) == 2
    assert transactions[0].family_id == family_id
    assert transactions[0].head_budget == 'Work'
    assert transactions[1].month == '2026-02'


def test_create_credit_card_payment_links_bank_transaction(
    app, card, family_id, patch_family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family_id)
    account = Account(
        family_id=family_id,
        name='Current',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    payment_category = Category(
        family_id=family_id,
        name='Card Payment',
        head_budget='Credit Cards',
        sub_budget=card.card_name,
        category_type='expense',
    )
    db.session.add_all([account, payment_category])
    db.session.commit()

    transactions = CreditCardService.create_transactions(card.id, {
        'txn_date': '2026-02-15',
        'txn_type': 'Payment',
        'txn_item': 'Payment',
        'txn_amount': '200.00',
        'category_id': '',
        'txn_fixed': '1',
        'txn_paid': '1',
        'is_recurring': '',
        'frequency': 'monthly',
        'occurrences': '1',
        'account_id': str(account.id),
    })

    bank_transaction = db.session.get(Transaction, transactions[0].bank_transaction_id)
    assert bank_transaction is not None
    assert bank_transaction.family_id == family_id
    assert bank_transaction.amount == Decimal('-200.00')
    assert bank_transaction.account_id == account.id


def test_credit_card_crud_assigns_family_and_updates_available_credit(
    app, family_id, patch_family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family_id)
    card = CreditCardService.create_card({
        'card_name': 'CRUD Card',
        'annual_apr': '24',
        'monthly_apr': '2',
        'min_payment_percent': '2',
        'credit_limit': '5000',
        'set_payment': '200',
        'statement_date': '15',
        'current_balance': '-1000',
        'is_active': 'on',
        'default_payment_account_id': '',
        'start_date': '2026-01-01',
        'purchase_0_percent_until': '2026-06-30',
        'balance_transfer_0_percent_until': '',
    })
    assert card.family_id == family_id
    assert card.available_credit == 6000

    updated = CreditCardService.update_card(card.id, {
        'card_name': 'Updated Card',
        'annual_apr': '25',
        'monthly_apr': '2.1',
        'min_payment_percent': '2',
        'credit_limit': '6000',
        'set_payment': '250',
        'statement_date': '20',
        'current_balance': '-1500',
        'is_active': 'on',
        'default_payment_account_id': '',
        'start_date': '2026-01-01',
        'purchase_0_percent_until': '',
        'balance_transfer_0_percent_until': '',
    })
    deleted_name = CreditCardService.delete_card(card.id)

    assert updated.card_name == 'Updated Card'
    assert updated.available_credit == 7500
    assert deleted_name == 'Updated Card'


def test_delete_credit_card_transaction_removes_linked_bank_transaction(
    app, card, family_id, patch_family
):
    account = Account(
        family_id=family_id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget='Payment', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    bank_transaction = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 1, 15)
    )
    db.session.add(bank_transaction)
    db.session.flush()
    card_transaction = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 15),
        item='Payment', transaction_type='Payment', amount=Decimal('100'),
        bank_transaction_id=bank_transaction.id
    )
    db.session.add(card_transaction)
    db.session.commit()

    deleted_card_id, account_id = CreditCardService.delete_transaction(
        card_transaction.id
    )

    assert deleted_card_id == card.id
    assert account_id == account.id
    assert db.session.get(CreditCardTransaction, card_transaction.id) is None
    assert db.session.get(Transaction, bank_transaction.id) is None


def test_toggle_credit_card_paid_locks_and_syncs_links(app, card, family_id, patch_family):
    account = Account(
        family_id=family_id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget='Payment', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    bank_transaction = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 1, 15), is_paid=False
    )
    db.session.add(bank_transaction)
    db.session.flush()
    card_transaction = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 15),
        item='Purchase', transaction_type='Purchase', amount=Decimal('-100'),
        is_paid=False, bank_transaction_id=bank_transaction.id
    )
    db.session.add(card_transaction)
    db.session.flush()
    expense = Expense(
        family_id=family_id, date=date(2026, 1, 15), description='Card expense',
        expense_type='Work', cost=100, total_cost=100,
        credit_card_transaction_id=card_transaction.id, paid_for=False
    )
    db.session.add(expense)
    db.session.commit()

    updated = CreditCardService.toggle_transaction_paid(card_transaction.id)

    assert updated.is_paid is True
    assert updated.is_fixed is True
    assert bank_transaction.is_paid is True
    assert expense.paid_for is True


def test_update_credit_card_transaction_rederives_date_fields(
    app, card, family_id, patch_family
):
    transaction = _add_purchase(card, Decimal('-50.00'), date(2026, 1, 1), family_id)

    updated = CreditCardService.update_transaction(transaction.id, {
        'txn_date': '2026-02-15',
        'txn_type': 'Purchase',
        'txn_item': 'Updated purchase',
        'txn_amount': '-75.00',
        'txn_fixed': '1',
        'txn_paid': '1',
    })

    assert updated.date == date(2026, 2, 15)
    assert updated.month == '2026-02'
    assert updated.day_name == 'Sunday'
    assert updated.amount == Decimal('-75.00')
    assert updated.item == 'Updated purchase'
    assert updated.is_fixed is True
    assert updated.is_paid is True


def test_update_payment_transaction_creates_linked_bank_transaction(
    app, card, family_id, patch_family
):
    account = Account(
        family_id=family_id, name='Payment Account', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget=card.card_name, category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.commit()
    payment = CreditCardService.create_transactions(card.id, {
        'txn_date': '2026-01-15', 'txn_type': 'Payment',
        'txn_item': 'Scheduled payment', 'txn_amount': '100',
        'category_id': '', 'txn_fixed': '0', 'txn_paid': '0',
        'is_recurring': '', 'occurrences': '1', 'account_id': '',
    })[0]

    updated, account_id = CreditCardService.update_payment_transaction(
        payment.id,
        {
            'payment_date': '2026-02-15',
            'payment_amount': '125',
            'account_id': str(account.id),
        },
    )

    bank_transaction = db.session.get(Transaction, updated.bank_transaction_id)
    assert account_id == account.id
    assert updated.amount == Decimal('125')
    assert updated.is_fixed is True
    assert bank_transaction.amount == Decimal('-125')
    assert bank_transaction.account_id == account.id
