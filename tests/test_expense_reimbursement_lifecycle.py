from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.expenses import Expense
from models.transactions import Transaction
from services.finance.expense_sync_service import ExpenseSyncService


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


def test_calendar_cutoff_period_handles_year_boundary(app, monkeypatch):
    monkeypatch.setattr(ExpenseSyncService, 'get_period_mode', lambda: 'calendar_month')
    monkeypatch.setattr(ExpenseSyncService, 'get_cutoff_day', lambda: 15)

    assert ExpenseSyncService._get_period_date_range('2026-01') == (
        date(2025, 12, 15),
        date(2026, 1, 14),
    )
