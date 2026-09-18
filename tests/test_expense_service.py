from decimal import Decimal

from extensions import db
from models.expenses import Expense
from services.expense_service import ExpenseService


def _expense_data(**overrides):
    data = {
        'date': '2026-04-15',
        'description': 'Client travel',
        'expense_type': 'Mileage',
        'credit_card_id': '',
        'account_id': '',
        'covered_miles': '20',
        'rate_per_mile': '0.45',
        'days': '2',
        'total_cost': '18.00',
        'vehicle_registration': 'AB12 CDE',
        'paid_for': 'on',
        'submitted': 'on',
        'reimbursed': '',
    }
    data.update(overrides)
    return data


def test_create_expense_assigns_family_and_date_fields(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    expense = ExpenseService.create_expense(_expense_data())

    assert expense.family_id == family.id
    assert expense.month == '2026-04'
    assert expense.finance_year == '2026-2027'
    assert expense.week == '16-2026'
    assert expense.total_cost == Decimal('18.00')


def test_update_expense_rederives_finance_year(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    expense = ExpenseService.create_expense(_expense_data())

    updated = ExpenseService.update_expense(
        expense.id,
        _expense_data(date='2026-03-31', total_cost='12.50', submitted=''),
    )

    assert updated.month == '2026-03'
    assert updated.finance_year == '2025-2026'
    assert updated.total_cost == Decimal('12.50')
    assert updated.submitted is False


def test_delete_expense_is_family_scoped(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    expense = ExpenseService.create_expense(_expense_data())

    ExpenseService.delete_expense(expense.id)

    assert db.session.get(Expense, expense.id) is None
