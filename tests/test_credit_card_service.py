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
from sqlalchemy import event
from werkzeug.datastructures import MultiDict

from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.categories import Category
from models.accounts import Account
from models.transactions import Transaction
from models.expenses import Expense
from models.family import Family
from models.settings import Settings
from services.finance.credit_card_service import CreditCardService
from services.finance.credit_card_payment_sync_service import CreditCardPaymentSyncService
from services.finance.credit_card_statement_service import CreditCardStatementService
from services.finance.balance_service import BalanceService
from services.finance import credit_card_statement_service


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
# CreditCardStatementService.calculate_interest
# ---------------------------------------------------------------------------

class TestCalculateInterest:
    def test_calculates_monthly_interest_correctly(self, app, card, patch_family):
        # 2% monthly on £1000 debt = £20
        result = CreditCardStatementService.calculate_interest(
            card.id, date(2026, 2, 15), balance_to_use=-1000.0
        )
        assert result == pytest.approx(20.0)

    def test_returns_zero_during_zero_percent_promo(self, app, card, patch_family):
        card.purchase_0_percent_until = date(2026, 12, 31)
        db.session.commit()
        result = CreditCardStatementService.calculate_interest(
            card.id, date(2026, 6, 15), balance_to_use=-1000.0
        )
        assert result == 0.0

    def test_returns_zero_for_zero_balance(self, app, card, patch_family):
        result = CreditCardStatementService.calculate_interest(
            card.id, date(2026, 2, 15), balance_to_use=0.0
        )
        assert result == 0.0


# ---------------------------------------------------------------------------
# CreditCardStatementService.generate_monthly_statement
# ---------------------------------------------------------------------------

class TestGenerateMonthlyStatement:
    def test_creates_interest_and_payment_when_balance_owed(
        self, app, card, family_id, patch_family
    ):
        _add_purchase(card, Decimal('-500.00'), date(2026, 2, 1), family_id)

        result = CreditCardStatementService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is not None, "Expected an interest transaction"
        assert result['payment_txn'] is not None, "Expected a payment transaction"
        # 2% of £500 = £10 interest (stored as negative — increases debt)
        assert float(result['interest_txn'].amount) == pytest.approx(-10.0)
        # Payment = min(set_payment=£200, balance=£510) = £200
        assert float(result['payment_txn'].amount) == pytest.approx(200.0)
        assert result['interest_txn'].vendor.name == card.card_name
        assert result['payment_txn'].vendor_id == result['interest_txn'].vendor_id

    def test_zero_interest_statement_created_during_promo(
        self, app, card, family_id, patch_family
    ):
        """A statement transaction IS created during a 0% promo — it records the statement
        period — but the amount should be £0 and marked as promotional rate."""
        card.purchase_0_percent_until = date(2026, 12, 31)
        db.session.commit()
        _add_purchase(card, Decimal('-500.00'), date(2026, 2, 1), family_id)

        result = CreditCardStatementService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is not None, \
            "A statement transaction should still be created during 0% period"
        assert float(result['interest_txn'].amount) == 0.0, \
            "Interest amount must be £0 during 0% promotional period"
        assert result['interest_txn'].is_promotional_rate is True, \
            "Transaction should be flagged as promotional rate"

    def test_no_payment_when_card_has_zero_balance(self, app, card, patch_family):
        result = CreditCardStatementService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['interest_txn'] is None
        assert result['payment_txn'] is None
        assert result['statement_balance'] == 0

    def test_payment_capped_at_outstanding_balance(
        self, app, card, family_id, patch_family
    ):
        # Debt is only £50 — set_payment is £200, so payment should be capped at £50
        _add_purchase(card, Decimal('-50.00'), date(2026, 2, 1), family_id)

        result = CreditCardStatementService.generate_monthly_statement(card.id, date(2026, 2, 15))

        assert result['payment_txn'] is not None
        assert float(result['payment_txn'].amount) <= 51.0  # at most balance + interest


def test_regeneration_replaces_unlocked_chain_and_preserves_locked_statement(
    app, card, family_id, patch_family, monkeypatch
):
    account = Account(
        family_id=family_id,
        name='Current',
        account_type='Joint',
        balance=0,
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()
    card.default_payment_account_id = account.id
    db.session.commit()
    monkeypatch.setattr(
        'services.finance.credit_card_statement_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    _add_purchase(card, Decimal('-500.00'), date(2026, 2, 1), family_id)

    february = CreditCardStatementService.generate_monthly_statement(
        card.id, date(2026, 2, 15)
    )
    march = CreditCardStatementService.generate_monthly_statement(
        card.id, date(2026, 3, 15)
    )
    february_statement_id = february['interest_txn'].id
    february_payment_id = february['payment_txn'].id
    february_bank_transaction_id = february['payment_txn'].bank_transaction_id
    march_statement_id = march['interest_txn'].id
    march['interest_txn'].is_fixed = True
    db.session.commit()

    result = CreditCardStatementService.regenerate_future_transactions(
        card.id,
        start_date=date(2026, 2, 15),
        end_date=date(2026, 3, 15),
    )

    assert result == {
        'deleted_count': 3,
        'statements_created': 1,
        'payments_created': 1,
    }
    assert db.session.get(CreditCardTransaction, february_statement_id) is None
    assert db.session.get(CreditCardTransaction, february_payment_id) is None
    assert db.session.get(Transaction, february_bank_transaction_id) is None
    assert db.session.get(CreditCardTransaction, march_statement_id).is_fixed is True
    replacement = db.session.query(CreditCardTransaction).filter_by(
        credit_card_id=card.id,
        date=date(2026, 2, 15),
        transaction_type='Interest',
    ).one()
    assert replacement.id != february_statement_id


def test_regenerate_all_future_transactions_aggregates_active_cards(
    app, card, family_id, patch_family
):
    _add_purchase(card, Decimal('-300.00'), date(2026, 2, 1), family_id)

    result = CreditCardStatementService.regenerate_all_future_transactions(
        start_date=date(2026, 2, 15),
        end_date=date(2026, 2, 15),
    )

    assert result['cards_processed'] == 1
    assert result['total_statements'] == 1
    assert result['total_payments'] == 1
    assert result['total_deleted'] == 0


@pytest.fixture
def auto_forecast_card(card, family_id, patch_family, monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 1, 1)

    monkeypatch.setattr('services.finance.credit_card_statement_service.date', FixedDate)
    monkeypatch.setattr(
        'services.finance.credit_card_statement_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    account = Account(
        family_id=family_id, name='Forecast account', account_type='Current', balance=0,
    )
    db.session.add(account)
    db.session.flush()
    card.default_payment_account_id = account.id
    card.monthly_apr = 0
    card.annual_apr = 0
    card.set_payment = 100
    Settings.set_value('default_generation_years', 1, setting_type='int')
    db.session.commit()
    return card


def _create_forecast_purchase(card, amount='-250', txn_date='2026-01-02'):
    return CreditCardService.create_transactions(card.id, {
        'txn_date': txn_date, 'txn_type': 'Purchase',
        'txn_item': 'Forecast purchase', 'txn_amount': amount,
    })[0]


def _forecast_payments(card):
    return CreditCardTransaction.query.filter_by(
        credit_card_id=card.id, transaction_type='Payment',
    ).order_by(CreditCardTransaction.date, CreditCardTransaction.id).all()


def test_add_edit_delete_automatically_rebuilds_statement_and_bank_forecasts(auto_forecast_card):
    card = auto_forecast_card
    purchase = _create_forecast_purchase(card)
    assert [payment.amount for payment in _forecast_payments(card)] == [100, 100, 50]
    account = db.session.get(Account, card.default_payment_account_id)
    assert account.balance == Decimal('-250')
    assert card.current_balance == 0

    CreditCardService.update_transaction(purchase.id, {
        'txn_date': '2026-01-03', 'txn_type': 'Purchase',
        'txn_item': 'Larger purchase', 'txn_amount': '-350',
    })
    payments = _forecast_payments(card)
    assert [payment.amount for payment in payments] == [100, 100, 100, 50]
    assert account.balance == Decimal('-350')
    assert all(payment.statement_id and payment.bank_transaction_id for payment in payments)
    assert all(payment.bank_transaction.amount == -payment.amount for payment in payments)

    CreditCardService.delete_transaction(purchase.id)
    assert _forecast_payments(card) == []
    assert CreditCardTransaction.query.filter_by(credit_card_id=card.id).count() == 0
    assert Transaction.query.filter_by(credit_card_id=card.id).count() == 0
    assert account.balance == 0


@pytest.mark.parametrize(('target', 'flag'), [
    ('statement', 'is_fixed'), ('statement', 'is_paid'),
    ('payment', 'is_fixed'), ('payment', 'is_paid'),
    ('bank', 'is_fixed'), ('bank', 'is_paid'),
])
def test_auto_and_manual_refresh_preserve_protected_statement_chains(
    auto_forecast_card, target, flag,
):
    card = auto_forecast_card
    _create_forecast_purchase(card)
    payment = _forecast_payments(card)[0]
    statement = db.session.get(CreditCardTransaction, payment.statement_id)
    bank = payment.bank_transaction
    setattr({'statement': statement, 'payment': payment, 'bank': bank}[target], flag, True)
    ids = statement.id, payment.id, bank.id
    amounts = statement.amount, payment.amount, bank.amount
    db.session.commit()

    _create_forecast_purchase(card, '-75')
    CreditCardStatementService.regenerate_future_transactions(
        card.id, start_date=date(2026, 1, 1), end_date=date(2027, 1, 1),
    )
    assert db.session.get(CreditCardTransaction, ids[0]) is statement
    assert db.session.get(CreditCardTransaction, ids[1]) is payment
    assert db.session.get(Transaction, ids[2]) is bank
    assert (statement.amount, payment.amount, bank.amount) == amounts
    assert len({payment.date for payment in _forecast_payments(card)}) == len(_forecast_payments(card))


def test_auto_refresh_continues_after_payoff_for_later_spending(auto_forecast_card):
    card = auto_forecast_card
    _create_forecast_purchase(card, '-50')
    _create_forecast_purchase(card, '-75', '2026-04-02')
    payments = _forecast_payments(card)
    assert [(payment.date, payment.amount) for payment in payments] == [
        (date(2026, 1, 29), Decimal('50')),
        (date(2026, 4, 29), Decimal('75')),
    ]


def test_spending_on_statement_day_has_a_reusable_statement_chain(auto_forecast_card):
    card = auto_forecast_card
    _create_forecast_purchase(card, '-50', '2026-01-15')
    payment = _forecast_payments(card)[0]
    assert payment.statement_id is not None
    assert payment.date == date(2026, 1, 29)
    CreditCardStatementService.refresh_after_changes([card.id])
    db.session.commit()
    assert len(_forecast_payments(card)) == 1
    assert _forecast_payments(card)[0].amount == 50


def test_changed_statement_day_does_not_duplicate_a_protected_month(auto_forecast_card):
    card = auto_forecast_card
    _create_forecast_purchase(card)
    payment = _forecast_payments(card)[0]
    payment.is_fixed = True
    card.statement_date = 20
    CreditCardStatementService.refresh_after_changes([card.id])
    db.session.commit()
    january_statements = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id, transaction_type='Interest', month='2026-01',
    ).all()
    assert len(january_statements) == 1
    assert january_statements[0].id == payment.statement_id
    assert [payment.amount for payment in _forecast_payments(card)] == [100, 100, 50]


def test_recurring_add_refreshes_once_and_manual_generation_remains_idempotent(
    auto_forecast_card, monkeypatch,
):
    card = auto_forecast_card
    original = CreditCardStatementService.regenerate_future_transactions
    calls = []

    def regenerate(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(CreditCardStatementService, 'regenerate_future_transactions', regenerate)
    CreditCardService.create_transactions(card.id, {
        'txn_date': '2026-01-02', 'txn_type': 'Purchase', 'txn_item': 'Recurring',
        'txn_amount': '-50', 'is_recurring': 'on', 'occurrences': '3',
        'frequency': 'monthly',
    })
    assert calls == [card.id]
    expected = [(payment.date, payment.amount) for payment in _forecast_payments(card)]
    CreditCardStatementService.regenerate_future_transactions(card.id)
    assert [(payment.date, payment.amount) for payment in _forecast_payments(card)] == expected


def test_generation_failure_rolls_back_purchase_and_generated_rows(auto_forecast_card, monkeypatch):
    card = auto_forecast_card
    original = CreditCardStatementService.generate_monthly_statement

    def fail_after_generating(*args, **kwargs):
        original(*args, **kwargs)
        raise ValueError('Forecast failed')

    monkeypatch.setattr(CreditCardStatementService, 'generate_monthly_statement', fail_after_generating)
    with pytest.raises(ValueError, match='Forecast failed'):
        _create_forecast_purchase(card)
    db.session.rollback()
    assert CreditCardTransaction.query.filter_by(credit_card_id=card.id).count() == 0
    assert Transaction.query.filter_by(credit_card_id=card.id).count() == 0


def test_month_end_statement_day_is_clamped_without_drifting(auto_forecast_card):
    card = auto_forecast_card
    card.statement_date = 31
    db.session.commit()
    _create_forecast_purchase(card)
    statements = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id, transaction_type='Interest',
    ).order_by(CreditCardTransaction.date).all()
    assert [statement.date for statement in statements] == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    ]


@pytest.mark.parametrize('disabled', ['inactive', 'no_statement_day'])
def test_automatic_generation_requires_active_card_and_statement_day(auto_forecast_card, disabled):
    card = auto_forecast_card
    if disabled == 'inactive':
        card.is_active = False
    else:
        card.statement_date = None
    db.session.commit()
    purchase = _create_forecast_purchase(card)
    assert _forecast_payments(card) == []
    assert purchase.balance == Decimal('-250')


def test_editing_bank_payment_refreshes_later_payments_without_replacing_override(auto_forecast_card):
    from services.finance.transaction_service import TransactionService

    card = auto_forecast_card
    _create_forecast_purchase(card)
    payment = _forecast_payments(card)[0]
    bank = payment.bank_transaction
    bank.amount = Decimal('-40')
    CreditCardPaymentSyncService.sync_bank_transaction_to_payment(bank)
    db.session.commit()
    assert payment.is_fixed is True
    assert payment.amount == 40
    assert [payment.amount for payment in _forecast_payments(card)] == [40, 100, 100, 10]
    assert db.session.get(Account, bank.account_id).balance == Decimal('-250')
    TransactionService.toggle_paid(bank.id)
    assert payment.is_paid is True
    assert payment.is_fixed is True
    assert card.current_balance == 40


def test_bank_payment_sync_updates_card_payment_without_committing(
    app, card, family_id, patch_family, monkeypatch,
):
    account = Account(
        family_id=family_id, name='Payment Account', account_type='Joint',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget=card.card_name, category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    bank = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        credit_card_id=card.id, amount=Decimal('-100'),
        transaction_date=date(2026, 1, 15), is_paid=False,
    )
    db.session.add(bank)
    db.session.flush()
    payment = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 15),
        item='Payment', transaction_type='Payment', amount=Decimal('100'),
        is_paid=False, is_fixed=False, bank_transaction_id=bank.id,
    )
    db.session.add(payment)
    db.session.commit()

    refreshed = []
    monkeypatch.setattr(
        CreditCardStatementService, 'refresh_after_changes',
        lambda card_ids, preserve_ids=(): refreshed.append(
            (list(card_ids), list(preserve_ids))
        ),
    )
    commits = []
    session = db.session()

    def record_commit(_session):
        commits.append(True)

    event.listen(session, 'after_commit', record_commit)
    try:
        bank.amount = Decimal('-42.50')
        bank.transaction_date = date(2026, 2, 15)
        bank.is_paid = True
        result = CreditCardPaymentSyncService.sync_bank_transaction_to_payment(bank)
        assert result is payment
        assert not commits
    finally:
        event.remove(session, 'after_commit', record_commit)

    assert payment.amount == Decimal('42.50')
    assert payment.date == date(2026, 2, 15)
    assert payment.day_name == 'Sunday'
    assert payment.week == '07-2026'
    assert payment.month == '2026-02'
    assert payment.is_paid is True
    assert payment.is_fixed is True
    assert payment.vendor.name == account.name
    assert refreshed == [([card.id], [payment.id])]
    db.session.commit()


def test_card_payment_sync_updates_bank_transaction_without_committing(
    app, card, family_id, patch_family, monkeypatch,
):
    account = Account(
        family_id=family_id, name='Payment Account', account_type='Joint',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget=card.card_name, category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    bank = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        credit_card_id=card.id, amount=Decimal('-100'),
        transaction_date=date(2026, 1, 15), is_paid=False, is_fixed=True,
    )
    db.session.add(bank)
    db.session.flush()
    payment = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 15),
        item='Payment', transaction_type='Payment', amount=Decimal('100'),
        is_paid=False, is_fixed=False, bank_transaction_id=bank.id,
    )
    db.session.add(payment)
    db.session.commit()

    recalculations = []
    monkeypatch.setattr(
        BalanceService, 'recalculate',
        lambda **kwargs: recalculations.append(kwargs),
    )
    commits = []
    session = db.session()

    def record_commit(_session):
        commits.append(True)

    event.listen(session, 'after_commit', record_commit)
    try:
        payment.amount = Decimal('125.50')
        payment.date = date(2026, 3, 7)
        payment.is_paid = True
        payment.is_fixed = False
        result = CreditCardPaymentSyncService.sync_payment_to_bank_transaction(payment)
        assert result is bank
        assert not commits
    finally:
        event.remove(session, 'after_commit', record_commit)

    assert bank.amount == Decimal('-125.50')
    assert bank.transaction_date == date(2026, 3, 7)
    assert bank.year_month == '2026-03'
    assert bank.week_year == '10-2026'
    assert bank.day_name == 'Sat'
    assert bank.is_paid is True
    assert bank.is_fixed is False
    assert bank.vendor.name == account.name
    assert recalculations == [{'account_ids': [account.id], 'commit': False}]
    db.session.commit()


def test_card_payment_sync_ignores_missing_and_paid_links(
    app, card, family_id, patch_family, monkeypatch,
):
    account = Account(
        family_id=family_id, name='Payment Account', account_type='Joint',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget=card.card_name, category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    paid_bank = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        credit_card_id=card.id, amount=Decimal('-100'),
        transaction_date=date(2026, 1, 15), is_paid=True,
    )
    orphan_bank = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        credit_card_id=card.id, amount=Decimal('-50'),
        transaction_date=date(2026, 1, 16), is_paid=False,
    )
    db.session.add_all([paid_bank, orphan_bank])
    db.session.flush()
    paid_payment = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 15),
        item='Paid payment', transaction_type='Payment', amount=Decimal('100'),
        is_paid=True, is_fixed=True, bank_transaction_id=paid_bank.id,
    )
    db.session.add(paid_payment)
    db.session.commit()

    refreshed = []
    recalculated = []
    monkeypatch.setattr(
        CreditCardStatementService, 'refresh_after_changes',
        lambda *args, **kwargs: refreshed.append((args, kwargs)),
    )
    monkeypatch.setattr(
        BalanceService, 'recalculate',
        lambda **kwargs: recalculated.append(kwargs),
    )

    assert CreditCardPaymentSyncService.sync_bank_transaction_to_payment(orphan_bank) is None
    assert CreditCardPaymentSyncService.sync_bank_transaction_to_payment(paid_bank) is None
    unlinked_payment = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 17),
        item='Unlinked payment', transaction_type='Payment', amount=Decimal('25'),
    )
    missing_bank_payment = CreditCardTransaction(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 18),
        item='Missing bank payment', transaction_type='Payment',
        amount=Decimal('30'), bank_transaction_id=999999,
    )
    assert CreditCardPaymentSyncService.sync_payment_to_bank_transaction(unlinked_payment) is None
    assert CreditCardPaymentSyncService.sync_payment_to_bank_transaction(missing_bank_payment) is None
    assert refreshed == []
    assert recalculated == []


def test_expense_purchase_changes_refresh_forecasts(auto_forecast_card, family_id):
    from services.finance.expense_sync_service import ExpenseSyncService

    card = auto_forecast_card
    expense = Expense(
        family_id=family_id, credit_card_id=card.id, date=date(2026, 1, 2),
        description='Work purchase', expense_type='Travel',
        cost=Decimal('250'), total_cost=Decimal('250'),
    )
    db.session.add(expense)
    db.session.commit()
    ExpenseSyncService.reconcile(expense.id)
    assert [payment.amount for payment in _forecast_payments(card)] == [100, 100, 50]
    expense.total_cost = Decimal('75')
    db.session.commit()
    ExpenseSyncService.reconcile(expense.id)
    assert [payment.amount for payment in _forecast_payments(card)] == [75]
    ExpenseSyncService.bulk_delete_linked_transactions([expense.id])
    assert _forecast_payments(card) == []


def test_card_subscription_updates_and_cancellation_refresh_payments(auto_forecast_card, monkeypatch):
    from services.finance.subscription_service import SubscriptionService

    card = auto_forecast_card
    monkeypatch.setattr(
        'services.finance.subscription_service.date',
        credit_card_statement_service.date,
    )
    subscription = SubscriptionService.create(MultiDict({
        'name': 'Streaming', 'amount': '50', 'target_type': 'credit_card',
        'credit_card_id': str(card.id), 'frequency': 'monthly',
        'start_date': '2026-01-02', 'end_date': '2026-03-02', 'horizon_years': '1',
    }))
    db.session.commit()
    assert [payment.amount for payment in _forecast_payments(card)] == [50, 50, 50]
    subscription.amount = Decimal('-75')
    SubscriptionService.sync_pending(subscription)
    db.session.commit()
    assert [payment.amount for payment in _forecast_payments(card)] == [75, 75, 75]
    SubscriptionService.cancel(subscription.id)
    db.session.commit()
    assert _forecast_payments(card) == []


def test_balance_transfer_refreshes_both_cards(auto_forecast_card, family_id):
    card = auto_forecast_card
    _create_forecast_purchase(card)
    destination = CreditCard(
        family_id=family_id, card_name='Destination', annual_apr=0, monthly_apr=0,
        credit_limit=5000, min_payment_percent=2, set_payment=100,
        statement_date=15, is_active=True,
    )
    db.session.add(destination)
    db.session.commit()
    transfer = CreditCardService.create_balance_transfer({
        'from_card_id': str(card.id), 'to_card_id': str(destination.id),
        'amount': '150', 'fee_percent': '0', 'transfer_date': '2026-01-03',
    })
    assert [payment.amount for payment in _forecast_payments(card)] == [100]
    assert [payment.amount for payment in _forecast_payments(destination)] == [100, 50]
    CreditCardService.delete_transaction(transfer['from_txn'].id)
    assert [payment.amount for payment in _forecast_payments(card)] == [100, 100, 50]
    assert _forecast_payments(destination) == []


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
        'assigned_to': 'Household',
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
    assert all(transaction.assigned_to == 'Household' for transaction in transactions)


def test_credit_card_transaction_assignment_update_clear_and_preserve(
    app, card, family_id, patch_family
):
    data = {
        'txn_date': '2026-01-15',
        'txn_type': 'Purchase',
        'txn_item': 'Groceries',
        'txn_amount': '-25.00',
        'assigned_to': 'Household',
    }
    transaction = CreditCardService.create_transactions(card.id, data)[0]
    assert transaction.assigned_to == 'Household'

    data['assigned_to'] = 'Child'
    CreditCardService.update_transaction(transaction.id, data)
    db.session.refresh(transaction)
    assert transaction.assigned_to == 'Child'

    del data['assigned_to']
    CreditCardService.update_transaction(transaction.id, data)
    assert transaction.assigned_to == 'Child'

    data['assigned_to'] = ''
    CreditCardService.update_transaction(transaction.id, data)
    db.session.refresh(transaction)
    assert transaction.assigned_to == ''


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
    assert transactions[0].vendor.name == account.name
    assert bank_transaction.vendor_id == transactions[0].vendor_id


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
    assert updated.vendor.name == account.name
    assert bank_transaction.vendor_id == updated.vendor_id


# ---------------------------------------------------------------------------
# CreditCardService.create_balance_transfer
# ---------------------------------------------------------------------------

@pytest.fixture
def second_card(app, family_id):
    c = CreditCard(
        family_id=family_id,
        card_name='Second Card',
        annual_apr=Decimal('20.0'),
        monthly_apr=Decimal('1.67'),
        credit_limit=Decimal('8000.00'),
        current_balance=Decimal('0.00'),
        min_payment_percent=Decimal('2.0'),
        default_transfer_fee_percent=Decimal('3.00'),
        is_active=True,
    )
    db.session.add(c)
    db.session.commit()
    return c


def test_create_balance_transfer_creates_linked_transactions_with_fee(
    app, card, second_card, family_id, patch_family
):
    result = CreditCardService.create_balance_transfer({
        'from_card_id': str(card.id),
        'to_card_id': str(second_card.id),
        'amount': '1000.00',
        'fee_percent': '3.00',
        'transfer_date': '2026-03-01',
        'is_paid': '1',
    })

    from_txn = result['from_txn']
    to_txn = result['to_txn']

    assert result['fee_amount'] == Decimal('30.00')
    assert from_txn.transaction_type == 'Balance Transfer'
    assert from_txn.amount == Decimal('1000.00')
    assert from_txn.credit_card_id == card.id
    assert to_txn.transaction_type == 'Balance Transfer'
    assert to_txn.amount == Decimal('-1030.00')
    assert to_txn.credit_card_id == second_card.id
    assert from_txn.linked_cc_transaction_id == to_txn.id
    assert to_txn.linked_cc_transaction_id == from_txn.id

    db.session.refresh(card)
    db.session.refresh(second_card)
    assert card.current_balance == Decimal('1000.00')
    assert second_card.current_balance == Decimal('-1030.00')


def test_create_balance_transfer_rejects_same_card(app, card, family_id, patch_family):
    with pytest.raises(ValueError):
        CreditCardService.create_balance_transfer({
            'from_card_id': str(card.id),
            'to_card_id': str(card.id),
            'amount': '100.00',
            'fee_percent': '0',
            'transfer_date': '2026-03-01',
        })


def test_delete_balance_transfer_transaction_removes_linked_pair(
    app, card, second_card, family_id, patch_family
):
    result = CreditCardService.create_balance_transfer({
        'from_card_id': str(card.id),
        'to_card_id': str(second_card.id),
        'amount': '500.00',
        'fee_percent': '2.00',
        'transfer_date': '2026-03-01',
        'is_paid': '1',
    })
    from_txn_id = result['from_txn'].id
    to_txn_id = result['to_txn'].id

    CreditCardService.delete_transaction(from_txn_id)

    assert db.session.get(CreditCardTransaction, from_txn_id) is None
    assert db.session.get(CreditCardTransaction, to_txn_id) is None


def test_private_credit_card_and_statement_hidden_but_shared_payment_txn_stays_visible(
    app, family_id, patch_family, monkeypatch
):
    """Private hides the card and its statement/transaction history, but a
    payment transaction posted to a shared account still appears there for
    the whole family."""
    from models.users import User
    from utils.db_helpers import family_query

    owner = User(
        email='owner@example.com', name='Owner', family_id=family_id, role='admin',
    )
    owner.set_password('TestPass1!')
    db.session.add(owner)
    db.session.commit()

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: owner.id)

    account = Account(
        family_id=family_id, name='Joint', account_type='Joint',
        balance=0, is_active=True,
    )
    db.session.add(account)
    db.session.commit()

    private_card = CreditCardService.create_card({
        'card_name': 'Private Card',
        'annual_apr': '24.0',
        'monthly_apr': '2.0',
        'credit_limit': '5000.00',
        'current_balance': '-200.00',
        'min_payment_percent': '2.0',
        'set_payment': '50.00',
        'statement_date': '15',
        'default_payment_account_id': str(account.id),
        'is_active': 'on',
        'visibility': 'private',
    })

    assert private_card.owner_id == owner.id
    assert private_card.is_private is True
    assert account.owner_id is None  # the account itself stays shared

    payment_txn = CreditCardStatementService.generate_payment_transaction(
        private_card.id, date(2026, 2, 15)
    )
    bank_transaction = db.session.get(Transaction, payment_txn.bank_transaction_id)

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: owner.id + 999)

    # The card and its statement/payment history are hidden from other family members...
    assert private_card not in family_query(CreditCard).all()
    assert payment_txn not in family_query(CreditCardTransaction).all()
    # ...but the bank payment transaction remains visible in the shared account.
    assert bank_transaction in family_query(Transaction).all()
