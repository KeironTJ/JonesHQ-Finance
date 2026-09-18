from datetime import date
from decimal import Decimal

from extensions import db
from models.recurring_income import RecurringIncome
from services.income_service import IncomeService


def test_create_recurring_income_assigns_family_and_persists_overrides(
    app, family, monkeypatch
):
    monkeypatch.setattr('services.income_service.get_family_id', lambda: family.id)

    recurring = IncomeService.create_recurring_income({
        'person': 'Household',
        'start_date': '2026-01-15',
        'end_date': '2026-12-15',
        'pay_day': '15',
        'gross_annual': '60000',
        'employer_pension_pct': '5',
        'employee_pension_pct': '3',
        'tax_code': '1257L',
        'avc': '50',
        'other': '10',
        'deposit_account_id': '',
        'category_id': '',
        'auto_create_transaction': 'on',
        'source': 'Employer',
        'description': 'Monthly salary',
        'use_manual_deductions': 'on',
        'manual_tax_monthly': '500',
        'manual_ni_monthly': '100',
        'manual_employee_pension': '150',
        'manual_employer_pension': '250',
        'manual_take_home': '4250',
    })

    assert recurring.family_id == family.id
    assert recurring.start_date == date(2026, 1, 15)
    assert recurring.end_date == date(2026, 12, 15)
    assert recurring.gross_annual_income == Decimal('60000')
    assert recurring.use_manual_deductions is True
    assert recurring.manual_take_home == Decimal('4250')
    assert db.session.get(RecurringIncome, recurring.id) is recurring
