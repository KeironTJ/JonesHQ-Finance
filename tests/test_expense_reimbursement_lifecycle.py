from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.expenses import Expense
from models.income import Income
from models.recurring_income import RecurringIncome
from models.transactions import Transaction
from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
from services.finance.expense_service import ExpenseService
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


def test_partial_reimbursement_excludes_other_members_private_and_foreign_expenses(
    app, family, user, monkeypatch,
):
    from models.family import Family
    from models.users import User

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [(date(2026, 4, 10), Decimal('10.00'))],
    )
    other_member = User(
        email='other@example.com', name='Other Member',
        family_id=family.id, role='member',
    )
    other_member.set_password('TestPass1!')
    other_family = Family(name='Other Family')
    db.session.add_all([other_member, other_family])
    db.session.flush()
    private_expense = Expense(
        family_id=family.id, date=date(2026, 4, 12),
        description='Private expense', expense_type='Travel',
        cost=Decimal('100.00'), total_cost=Decimal('100.00'),
        reimbursement_group_id=group.id, owner_id=other_member.id,
    )
    foreign_group = ExpenseReimbursementGroup(
        family_id=other_family.id, name='Foreign', mode='separate',
        is_default=True,
    )
    db.session.add(foreign_group)
    db.session.flush()
    foreign_expense = Expense(
        family_id=other_family.id, date=date(2026, 4, 13),
        description='Foreign expense', expense_type='Travel',
        cost=Decimal('200.00'), total_cost=Decimal('200.00'),
        reimbursement_group_id=foreign_group.id,
    )
    db.session.add_all([private_expense, foreign_expense])
    db.session.commit()

    result = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )

    assert result[1] == Decimal('10.00')
    assert expenses[0].claim_group == result[2]
    assert private_expense.claim_group is None
    assert foreign_expense.claim_group is None


def test_partial_reimbursement_suffix_counts_other_members_private_claims(
    app, family, user, monkeypatch,
):
    from models.users import User

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    _group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [(date(2026, 4, 10), Decimal('10.00'))],
    )
    other_member = User(
        email='other@example.com', name='Other Member',
        family_id=family.id, role='member',
    )
    other_member.set_password('TestPass1!')
    db.session.add(other_member)
    db.session.flush()
    private_expense = Expense(
        family_id=family.id, date=date(2026, 4, 12),
        description='Private partial claim', expense_type='Travel',
        cost=Decimal('5.00'), total_cost=Decimal('5.00'),
        owner_id=other_member.id, claim_group='2026-04-P1',
    )
    db.session.add(private_expense)
    db.session.commit()

    result = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )

    assert result[2] == '2026-04-P2'
    assert expenses[0].claim_group == '2026-04-P2'
    assert private_expense.claim_group == '2026-04-P1'


def test_partial_reimbursement_updates_when_expense_amount_changes(
    app, family, monkeypatch,
):
    _group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    transaction_id, _, _ = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )
    transaction = db.session.get(Transaction, transaction_id)
    account = db.session.get(Account, transaction.account_id)
    assert account.balance == Decimal('30.00')

    ExpenseService.update_expense(
        expenses[0].id,
        {'total_cost': '25.00'},
    )

    assert transaction.amount == Decimal('45.00')
    assert account.balance == Decimal('45.00')


def test_partial_reimbursement_updates_and_removes_after_expense_deletion(
    app, family, monkeypatch,
):
    _group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    transaction_id, _, _ = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )
    transaction = db.session.get(Transaction, transaction_id)
    account = db.session.get(Account, transaction.account_id)

    ExpenseService.delete_expense(expenses[0].id)
    assert transaction.amount == Decimal('20.00')
    assert account.balance == Decimal('20.00')

    ExpenseService.delete_expense(expenses[1].id)
    assert db.session.get(Transaction, transaction_id) is None
    assert account.balance == Decimal('0')


def test_partial_reimbursement_updates_and_removes_when_expenses_are_unclaimed(
    app, family, monkeypatch,
):
    _group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    transaction_id, _, _ = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )
    transaction = db.session.get(Transaction, transaction_id)

    ExpenseService.set_period(expenses[0].id, 'auto')
    assert transaction.amount == Decimal('20.00')

    ExpenseService.set_period(expenses[1].id, 'auto')
    assert db.session.get(Transaction, transaction_id) is None


def test_paid_partial_reimbursement_blocks_expense_mutations_atomically(
    app, family, monkeypatch,
):
    _group, expenses = _create_reimbursement_fixtures(
        family, monkeypatch, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    transaction_id, _, _ = ExpenseSyncService.create_partial_reimbursement(
        date(2026, 4, 1), date(2026, 4, 30), date(2026, 5, 1),
    )
    transaction = db.session.get(Transaction, transaction_id)
    transaction.is_paid = True
    db.session.commit()

    with pytest.raises(ValueError, match='already paid'):
        ExpenseService.update_expense(
            expenses[0].id,
            {'total_cost': '25.00'},
        )
    with pytest.raises(ValueError, match='already paid'):
        ExpenseService.delete_expense(expenses[0].id)
    with pytest.raises(ValueError, match='already paid|settled'):
        ExpenseService.set_period(expenses[0].id, 'auto')
    with pytest.raises(ValueError, match='already paid'):
        ExpenseService.bulk_delete_expenses([expenses[0].id, expenses[1].id])

    assert db.session.get(Expense, expenses[0].id).total_cost == Decimal('10.00')
    assert db.session.get(Expense, expenses[1].id).total_cost == Decimal('20.00')
    assert db.session.get(Transaction, transaction_id).amount == Decimal('30.00')
    assert db.session.get(Transaction, transaction_id).is_paid is True


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
