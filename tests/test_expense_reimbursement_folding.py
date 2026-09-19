from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.expenses import Expense
from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
from services.finance.expense_service import ExpenseService
from services.finance.expense_sync_service import ExpenseSyncService
from services.finance.income_service import IncomeService


def _make_account(family):
    account = Account(family_id=family.id, name='Main', account_type='Current')
    db.session.add(account)
    db.session.commit()
    return account


def test_folded_expense_is_not_reimbursed_until_payslip_is_paid(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = _make_account(family)

    recurring = IncomeService.create_recurring_income({
        'person': 'Keiron',
        'start_date': '2026-04-01',
        'pay_day': '15',
        'gross_annual': '30000',
        'tax_code': '1257L',
        'deposit_account_id': str(account.id),
        'auto_create_transaction': 'on',
        'source': 'Acme Ltd',
    })
    ExpenseReimbursementGroupService.set_folding_for_recurring_income(recurring.id, True)
    group = ExpenseReimbursementGroupService.get_folded_group_for_recurring_income(recurring.id)

    income = IncomeService.create_income_record(
        person='Keiron', pay_date=date(2026, 4, 15), gross_annual=Decimal('30000'),
        tax_code='1257L', deposit_account_id=account.id, create_transaction=True,
        recurring_income_id=recurring.id,
    )
    assert income.is_paid is False

    expense = ExpenseService.create_expense({
        'date': '2026-04-10',
        'description': 'Client lunch',
        'expense_type': 'Food',
        'account_id': str(account.id),
        'total_cost': '25.00',
        'reimbursement_group_id': str(group.id),
    })

    ExpenseSyncService.reconcile_monthly_reimbursements()
    db.session.refresh(expense)
    assert expense.reimbursed is False, "expense must not be marked reimbursed before the payslip is paid"

    income.is_paid = True
    db.session.commit()
    IncomeService._sync_folded_expenses(income)
    db.session.refresh(expense)
    assert expense.reimbursed is True

    income.is_paid = False
    db.session.commit()
    IncomeService._sync_folded_expenses(income)
    db.session.refresh(expense)
    assert expense.reimbursed is False, "unmarking the payslip as paid should un-reimburse its folded expenses"
