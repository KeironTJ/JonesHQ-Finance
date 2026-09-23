from datetime import date
from decimal import Decimal

from extensions import db
from models.recurring_income import RecurringIncome
from models.income import Income
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from services.finance.income_service import IncomeService


def test_create_recurring_income_assigns_family_and_persists_overrides(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

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


def test_update_and_delete_recurring_income(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    recurring = IncomeService.create_recurring_income({
        'person': 'Household',
        'start_date': '2026-01-15',
        'end_date': '',
        'pay_day': '15',
        'gross_annual': '50000',
        'employer_pension_pct': '0',
        'employee_pension_pct': '0',
        'tax_code': '1257L',
        'avc': '0',
        'other': '0',
        'deposit_account_id': '',
        'category_id': '',
        'auto_create_transaction': 'on',
        'source': 'Old Employer',
        'description': 'Old salary',
        'use_manual_deductions': '',
    })
    updated = IncomeService.update_recurring_income(recurring.id, {
        'person': 'Household',
        'start_date': '2026-02-15',
        'end_date': '2027-02-15',
        'pay_day': '20',
        'gross_annual': '55000',
        'employer_pension_pct': '5',
        'employee_pension_pct': '3',
        'tax_code': '1257L',
        'avc': '10',
        'other': '5',
        'deposit_account_id': '',
        'category_id': '',
        'auto_create_transaction': '',
        'source': 'New Employer',
        'description': 'New salary',
        'is_active': 'on',
        'use_manual_deductions': '',
    })
    IncomeService.delete_recurring_income(recurring.id)

    assert updated.gross_annual_income == Decimal('55000')
    assert updated.pay_day == 20
    assert updated.source == 'New Employer'
    assert db.session.get(RecurringIncome, recurring.id) is None


def test_income_deletion_cleans_or_keeps_linked_transactions(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(
        family_id=family.id, name='Income Account', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Salary', head_budget='Income',
        sub_budget='Salary', category_type='income'
    )
    db.session.add_all([account, category])
    db.session.flush()
    kept_transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('1000'), transaction_date=date(2026, 1, 15)
    )
    deleted_transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('1000'), transaction_date=date(2026, 2, 15)
    )
    db.session.add_all([kept_transaction, deleted_transaction])
    db.session.flush()
    first = Income(
        family_id=family.id, person='Household', pay_date=date(2026, 1, 15),
        tax_year='2025-2026', gross_annual_income=12000,
        gross_monthly_income=1000, take_home=1000,
        transaction_id=kept_transaction.id
    )
    second = Income(
        family_id=family.id, person='Household', pay_date=date(2026, 2, 15),
        tax_year='2025-2026', gross_annual_income=12000,
        gross_monthly_income=1000, take_home=1000,
        transaction_id=deleted_transaction.id
    )
    db.session.add_all([first, second])
    db.session.commit()

    IncomeService.delete_income_record(first.id, keep_transaction=True)
    deleted_count = IncomeService.delete_income_records([second.id])

    assert deleted_count == 1
    assert db.session.get(Transaction, kept_transaction.id) is not None
    assert db.session.get(Income, first.id) is None
    assert db.session.get(Transaction, deleted_transaction.id) is None


def test_private_income_record_hidden_from_other_family_members(app, family, monkeypatch, user):
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    income = IncomeService.create_income_record(
        person='Keiron',
        pay_date=date(2026, 1, 15),
        gross_annual=50000,
        deposit_account_id=None,
        create_transaction=False,
        owner_id=user.id,
    )

    assert income.owner_id == user.id
    assert income in family_query(Income).all()

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)
    assert income not in family_query(Income).all()


def test_recurring_income_privacy_is_inherited_by_generated_records(app, family, monkeypatch, user):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    recurring = IncomeService.create_recurring_income({
        'person': 'Keiron',
        'start_date': '2026-01-15',
        'pay_day': '15',
        'gross_annual': '50000',
        'employer_pension_pct': '0',
        'employee_pension_pct': '0',
        'tax_code': '1257L',
        'avc': '0',
        'other': '0',
        'deposit_account_id': '',
        'category_id': '',
        'source': 'Employer',
        'visibility': 'private',
    })

    assert recurring.owner_id == user.id
    assert recurring.is_private is True

    generated = IncomeService.generate_missing_income(
        recurring.id, end_date=date(2026, 1, 1)
    )

    assert len(generated) == 1
    assert generated[0].owner_id == user.id

    from utils.db_helpers import family_query
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)
    assert generated[0] not in family_query(Income).all()
    assert recurring not in family_query(RecurringIncome).all()


def test_private_income_deposited_into_shared_account_stays_visible_as_a_transaction(
    app, family, monkeypatch, user
):
    """Private hides the Income record's details (salary/tax breakdown), but a
    shared account still shows every transaction in it to the whole family —
    including the deposit from a private income record."""
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    shared_account = Account(
        family_id=family.id, name='Joint', account_type='Joint',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=family.id, name='Groceries', head_budget='Expenses',
        sub_budget='Groceries', category_type='expense',
    )
    db.session.add_all([shared_account, category])
    db.session.flush()

    other_transaction = Transaction(
        family_id=family.id, account_id=shared_account.id,
        category_id=category.id, amount=Decimal('50'),
        transaction_date=date(2026, 1, 10), description='Groceries',
    )
    db.session.add(other_transaction)
    db.session.commit()

    income = IncomeService.create_income_record(
        person='Keiron',
        pay_date=date(2026, 1, 15),
        gross_annual=50000,
        deposit_account_id=shared_account.id,
        create_transaction=True,
        owner_id=user.id,
    )
    salary_transaction = db.session.get(Transaction, income.transaction_id)

    assert shared_account.owner_id is None  # the account itself stays shared

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)

    # The Income record's details are hidden from other family members...
    assert income not in family_query(Income).all()
    # ...but both transactions in the shared account remain visible to everyone.
    visible_transactions = family_query(Transaction).all()
    assert other_transaction in visible_transactions
    assert salary_transaction in visible_transactions
