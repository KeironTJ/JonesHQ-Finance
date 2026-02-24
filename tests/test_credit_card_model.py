"""
Unit tests for CreditCard model methods.

These tests do not touch the database — they instantiate CreditCard objects
directly and call their methods.
"""
from datetime import date
from decimal import Decimal

from models.credit_cards import CreditCard


def _card(**overrides):
    """Build an unsaved CreditCard with sensible defaults."""
    defaults = dict(
        card_name='Test Card',
        annual_apr=Decimal('24.0'),
        monthly_apr=Decimal('2.0'),
        credit_limit=Decimal('5000.00'),
        current_balance=Decimal('0.00'),
        min_payment_percent=Decimal('2.0'),
        set_payment=None,
        is_active=True,
    )
    defaults.update(overrides)
    return CreditCard(**defaults)


# ---------------------------------------------------------------------------
# get_current_purchase_apr
# ---------------------------------------------------------------------------

class TestGetCurrentPurchaseApr:
    def test_returns_monthly_apr_with_no_promo(self):
        assert _card().get_current_purchase_apr(date(2026, 1, 1)) == 2.0

    def test_returns_zero_during_active_promo(self):
        card = _card(purchase_0_percent_until=date(2026, 12, 31))
        assert card.get_current_purchase_apr(date(2026, 6, 1)) == 0.0

    def test_returns_zero_on_the_last_day_of_promo(self):
        # The boundary: on the expiry date itself 0% still applies (<=)
        card = _card(purchase_0_percent_until=date(2026, 6, 30))
        assert card.get_current_purchase_apr(date(2026, 6, 30)) == 0.0

    def test_returns_monthly_apr_day_after_promo_expires(self):
        card = _card(purchase_0_percent_until=date(2026, 6, 30))
        assert card.get_current_purchase_apr(date(2026, 7, 1)) == 2.0


# ---------------------------------------------------------------------------
# calculate_actual_payment
# ---------------------------------------------------------------------------

class TestCalculateActualPayment:
    def test_returns_zero_when_balance_is_positive(self):
        card = _card(current_balance=Decimal('100.00'), set_payment=Decimal('200.00'))
        assert card.calculate_actual_payment() == 0.0

    def test_returns_zero_when_balance_is_zero(self):
        assert _card().calculate_actual_payment() == 0.0

    def test_uses_set_payment_when_debt_exceeds_it(self):
        card = _card(current_balance=Decimal('-1000.00'), set_payment=Decimal('200.00'))
        assert card.calculate_actual_payment() == 200.0

    def test_caps_payment_at_outstanding_balance(self):
        # Debt is only £50 but set_payment is £200 — should only pay what's owed
        card = _card(current_balance=Decimal('-50.00'), set_payment=Decimal('200.00'))
        assert card.calculate_actual_payment() == 50.0

    def test_falls_back_to_minimum_when_no_set_payment(self):
        # 2% of £1000 = £20
        card = _card(current_balance=Decimal('-1000.00'), set_payment=None)
        assert card.calculate_actual_payment() == 20.0


# ---------------------------------------------------------------------------
# calculate_minimum_payment
# ---------------------------------------------------------------------------

class TestCalculateMinimumPayment:
    def test_calculates_percentage_of_outstanding_balance(self):
        card = _card(current_balance=Decimal('-500.00'), min_payment_percent=Decimal('2.0'))
        assert card.calculate_minimum_payment() == 10.0

    def test_returns_zero_when_balance_is_zero(self):
        assert _card(current_balance=Decimal('0.00')).calculate_minimum_payment() == 0.0

    def test_returns_zero_when_card_is_in_credit(self):
        assert _card(current_balance=Decimal('50.00')).calculate_minimum_payment() == 0.0
