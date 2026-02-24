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
from models.family import Family
from services.credit_card_service import CreditCardService


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
