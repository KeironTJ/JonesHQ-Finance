from decimal import Decimal

from extensions import db
from models.loan_payments import LoanPayment
from models.loans import Loan
from services.loan_service import LoanService


def test_create_loan_assigns_family_and_generates_schedule(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    loan, payments = LoanService.create_loan({
        'name': 'Test Loan',
        'loan_value': '1000.00',
        'current_balance': '1000.00',
        'annual_apr': '12.00',
        'monthly_payment': '100.00',
        'start_date': '2026-01-15',
        'term_months': '12',
        'default_payment_account_id': '',
        'weekend_adjustment': 'none',
        'is_active': 'on',
    })

    assert loan.family_id == family.id
    assert loan.end_date.isoformat() == '2027-01-15'
    assert loan.monthly_apr == Decimal('1.00')
    assert payments
    assert payments[0].period == 0
    assert LoanPayment.query.filter_by(loan_id=loan.id).count() == len(payments)
    assert db.session.get(Loan, loan.id).current_balance <= Decimal('1000.00')
