from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.expenses import Expense
from models.income import Income
from models.recurring_income import RecurringIncome
from models.transactions import Transaction
from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
from services.finance.expense_sync_service import ExpenseSyncService
from services.finance.income_service import IncomeService


def _create_reimbursement_fixtures(family, monkeypatch, expenses):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0,
    )
    category = Category(
        family_id=family.id, name='Reimbursement', head_budget='Income',
        sub_budget='Expense', category_type='income',
    )
    group = ExpenseReimbursementGroup(
        family_id=family.id, name='Default', mode='separate', is_default=True,
    )
    db.session.add_all([account, category, group])
    db.session.flush()
    rows = [
        Expense(
            family_id=family.id, date=expense_date,
            description=f'Expense {index}', expense_type='Travel',
            cost=amount, total_cost=amount, reimbursement_group_id=group.id,
        )
        for index, (expense_date, amount) in enumerate(expenses, start=1)
    ]
    db.session.add_all(rows)
    db.session.commit()
    return group, rows


def test_partial_reimbursement_reconciles_remaining_period_amount(app, family, monkeypatch):
    group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )

    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    full_reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
    ).one()
    assert full_reimbursement.amount == Decimal('30.00')
    assert ExpenseSyncService.reconcile_monthly_reimbursements(
        year_month='2026-04',
    ) == {}

    partial_result = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 15), date(2026, 4, 16),
    )

    partial_id, partial_amount, claim_group = partial_result
    assert partial_amount == Decimal('10.00')
    assert claim_group == '2026-04-P1'
    assert expenses[0].claim_group == claim_group
    assert expenses[1].claim_group == '2026-04'
    assert db.session.get(Transaction, partial_id).amount == Decimal('10.00')
    assert db.session.get(Transaction, full_reimbursement.id).amount == Decimal('20.00')
    assert ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 15), date(2026, 4, 16),
    ) is None


def test_partial_reimbursement_reconciles_each_affected_period(app, family, monkeypatch):
    group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
            (date(2026, 5, 10), Decimal('15.00')),
            (date(2026, 5, 20), Decimal('30.00')),
        ],
    )
    ExpenseSyncService.reconcile_monthly_reimbursements()
    assert {
        row.year_month: row.amount
        for row in Transaction.query.filter_by(
            payment_type='Expense Reimbursement',
            reimbursement_group_id=group.id,
        ).all()
    } == {'2026-04': Decimal('30.00'), '2026-05': Decimal('45.00')}

    partial_id, partial_total, claim_group = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 5, 15), date(2026, 5, 18),
    )

    assert partial_total == Decimal('45.00')
    assert claim_group == '2026-04-P1'
    assert [expense.claim_group for expense in expenses] == [
        claim_group, claim_group, claim_group, '2026-05',
    ]
    assert db.session.get(Transaction, partial_id).year_month == '2026-04'
    assert Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).first() is None
    may_reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-05',
    ).one()
    assert may_reimbursement.amount == Decimal('30.00')


def test_partial_reimbursement_updates_folded_payslip_and_unlinks_claimed_expense(
    app, family, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Current', account_type='Joint', balance=0,
    )
    db.session.add(account)
    db.session.commit()
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
    group = ExpenseReimbursementGroupService.set_folding_for_recurring_income(
        recurring.id, True,
    )
    income = IncomeService.create_income_record(
        person='Keiron', pay_date=date(2026, 4, 15),
        gross_annual=Decimal('30000'), tax_code='1257L',
        deposit_account_id=account.id, create_transaction=True,
        recurring_income_id=recurring.id,
    )
    first = Expense(
        family_id=family.id, date=date(2026, 4, 10),
        description='First claim', expense_type='Travel',
        cost=Decimal('10.00'), total_cost=Decimal('10.00'),
        reimbursement_group_id=group.id,
    )
    remaining = Expense(
        family_id=family.id, date=date(2026, 4, 20),
        description='Remaining claim', expense_type='Travel',
        cost=Decimal('20.00'), total_cost=Decimal('20.00'),
        reimbursement_group_id=group.id,
    )
    db.session.add_all([first, remaining])
    db.session.commit()

    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    assert income.expense_reimbursement_total == Decimal('30.00')
    original_take_home = income.take_home
    income_transaction = db.session.get(Transaction, income.transaction_id)
    assert income_transaction.amount == original_take_home + Decimal('30.00')

    partial_id, partial_total, claim_group = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 15), date(2026, 4, 16),
    )

    assert partial_total == Decimal('10.00')
    assert claim_group == '2026-04-P1'
    assert db.session.get(Transaction, partial_id).amount == Decimal('10.00')
    assert income.expense_reimbursement_total == Decimal('20.00')
    assert income_transaction.amount == original_take_home + Decimal('20.00')
    assert first.claim_group == claim_group
    assert first.income_id is None
    assert first.reimbursed is False
    assert remaining.income_id == income.id

    second_partial_id, second_partial_total, second_claim_group = (
        ExpenseSyncService.create_partial_reimbursement(
            date(2026, 4, 16), date(2026, 4, 30), date(2026, 5, 1),
        )
    )
    assert second_partial_total == Decimal('20.00')
    assert second_claim_group == '2026-04-P2'
    assert db.session.get(Transaction, second_partial_id).amount == Decimal('20.00')
    assert income.expense_reimbursement_total == Decimal('0.00')
    assert income_transaction.amount == original_take_home
    assert remaining.income_id is None
    assert remaining.reimbursed is False

    income.is_paid = True
    db.session.commit()
    IncomeService._sync_folded_expenses(income)
    db.session.refresh(first)
    db.session.refresh(remaining)
    assert first.reimbursed is False
    assert remaining.reimbursed is False


def test_partial_reimbursement_reconciles_every_affected_group(
    app, family, monkeypatch,
):
    group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    other_group = ExpenseReimbursementGroup(
        family_id=family.id, name='Other employer', mode='separate',
        is_default=False,
    )
    db.session.add(other_group)
    db.session.flush()
    other_expense = Expense(
        family_id=family.id, date=date(2026, 4, 11),
        description='Other employer expense', expense_type='Travel',
        cost=Decimal('50.00'), total_cost=Decimal('50.00'),
        reimbursement_group_id=other_group.id,
    )
    remaining_other_expense = Expense(
        family_id=family.id, date=date(2026, 4, 20),
        description='Other employer remaining expense', expense_type='Travel',
        cost=Decimal('70.00'), total_cost=Decimal('70.00'),
        reimbursement_group_id=other_group.id,
    )
    db.session.add_all([other_expense, remaining_other_expense])
    db.session.commit()
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    original_other = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=other_group.id,
    ).one()

    ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 15), date(2026, 4, 16),
    )

    assert expenses[0].claim_group == '2026-04-P1'
    assert expenses[1].claim_group == '2026-04'
    assert other_expense.claim_group == '2026-04-P1'
    assert remaining_other_expense.claim_group == '2026-04'
    assert db.session.get(Transaction, original_other.id).amount == Decimal('70.00')


def test_calendar_cutoff_period_handles_year_boundary(app, monkeypatch):
    monkeypatch.setattr(ExpenseSyncService, 'get_period_mode', lambda: 'calendar_month')
    monkeypatch.setattr(ExpenseSyncService, 'get_cutoff_day', lambda: 15)

    assert ExpenseSyncService._get_period_date_range('2026-01') == (
        date(2025, 12, 15),
        date(2026, 1, 14),
    )
