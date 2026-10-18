"""Regression tests for the Phase 0 income fixes (business logic + security)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.income import Income
from models.recurring_income import RecurringIncome
from models.transactions import Transaction
from models.users import User
from services.finance.income_service import IncomeService, GENERATION_HORIZON_YEARS


@pytest.fixture
def scoped(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    return family


@pytest.fixture
def account(scoped):
    acc = Account(family_id=scoped.id, name='Current', account_type='Joint', balance=0, is_active=True)
    db.session.add(acc)
    db.session.commit()
    return acc


def _template(**overrides):
    data = {
        'person': 'Household',
        'start_date': '2026-01-01',
        'end_date': '',
        'pay_day': '15',
        'gross_annual': '30000',
        'employer_pension_pct': '0',
        'employee_pension_pct': '0',
        'tax_code': '1257L',
        'deposit_account_id': '',
        'category_id': '',
        'source': 'Employer',
    }
    data.update(overrides)
    return IncomeService.create_recurring_income(data)


# --- B1/B2: one calculation everywhere -------------------------------------

def test_record_and_preview_and_edit_agree(scoped):
    income = IncomeService.create_income_record(
        person='Household', pay_date=date(2026, 5, 15), gross_annual=50000,
        employee_pension_pct=5, employer_pension_pct=3, create_transaction=False,
    )
    preview = IncomeService.preview_payslip({
        'gross_annual': '50000', 'employee_pension_pct': '5', 'employer_pension_pct': '3',
        'tax_code': '1257L', 'pay_date': '2026-05-15',
    })
    edited = IncomeService.update_income_record(income.id, {
        'pay_date': '2026-05-15', 'gross_annual': '50000', 'employee_pension_pct': '5',
        'employer_pension_pct': '3', 'tax_code': '1257L', 'person': 'Household',
    })

    assert Decimal(str(preview['take_home'])) == edited.take_home
    assert Decimal(str(preview['income_tax'])) == edited.income_tax
    # Pension is only removed once: taxable pay = 50,000 - 12 x 208.33
    assert edited.income_tax == Decimal('582.17')
    assert edited.tax_year == '2026-2027'


def test_tax_year_uses_6_april(scoped):
    income = IncomeService.create_income_record(
        person='Household', pay_date=date(2026, 4, 3), gross_annual=30000, create_transaction=False,
    )
    assert income.tax_year == '2025-2026'


# --- B7: two jobs paid the same day -----------------------------------------

def test_two_jobs_paid_on_same_day_both_generate(scoped):
    first = _template(source='Day job')
    second = _template(source='Weekend job', gross_annual='8000')

    IncomeService.generate_missing_income(first.id, end_date=date(2026, 1, 1))
    IncomeService.generate_missing_income(second.id, end_date=date(2026, 1, 1))

    rows = Income.query.filter_by(family_id=scoped.id).all()
    assert {r.recurring_income_id for r in rows} == {first.id, second.id}


def test_pay_dates_outside_template_dates_are_skipped(scoped):
    recurring = _template(start_date='2026-01-20', end_date='2026-03-10', pay_day='15')
    generated = IncomeService.generate_missing_income(recurring.id)
    assert [i.pay_date.month for i in generated] == [2]


# --- B8: deleting a range removes the forecast transaction ---------------------

def test_delete_range_removes_forecast_transactions(scoped, account):
    start = date.today().replace(day=1) + relativedelta(months=2)
    recurring = _template(
        start_date=start.isoformat(), deposit_account_id=str(account.id), auto_create_transaction='on',
    )
    IncomeService.generate_missing_income(recurring.id, end_date=start + relativedelta(months=2))
    assert Transaction.query.filter_by(account_id=account.id).count() == 3

    result = IncomeService.delete_income_range(recurring.id, start, start + relativedelta(months=3))

    assert result['deleted'] == 3
    assert Transaction.query.filter_by(account_id=account.id).count() == 0
    assert db.session.get(Account, account.id).balance == 0
    assert recurring.last_generated_date == start - relativedelta(months=1)


def test_regenerate_range_does_not_double_count(scoped, account):
    start = date.today().replace(day=1) + relativedelta(months=2)
    recurring = _template(
        start_date=start.isoformat(), deposit_account_id=str(account.id), auto_create_transaction='on',
    )
    end = start + relativedelta(months=1, days=27)
    IncomeService.generate_missing_income(recurring.id, end_date=end)
    IncomeService.regenerate_income_range(recurring.id, start, end)
    assert Transaction.query.filter_by(account_id=account.id).count() == 2


# --- B9: deleting a template ---------------------------------------------------

def test_delete_recurring_keeps_history_and_clears_forecasts(scoped, account):
    recurring = _template(
        start_date=(date.today() - relativedelta(months=2)).replace(day=1).isoformat(),
        deposit_account_id=str(account.id), auto_create_transaction='on',
    )
    IncomeService.generate_missing_income(recurring.id, end_date=date.today() + relativedelta(months=3))
    group = ExpenseReimbursementGroup(
        family_id=scoped.id, name='Payslip', mode='folded', recurring_income_id=recurring.id,
    )
    db.session.add(group)
    db.session.commit()
    paid = Income.query.filter(Income.pay_date <= date.today()).all()
    for income in paid:
        income.is_paid = True
    db.session.commit()
    paid_ids = {i.id for i in paid}

    IncomeService.delete_recurring_income(recurring.id)

    remaining = Income.query.filter_by(family_id=scoped.id).all()
    assert {i.id for i in remaining} == paid_ids
    assert all(i.recurring_income_id is None for i in remaining)
    assert Transaction.query.filter(Transaction.transaction_date > date.today()).count() == 0
    assert group.mode == 'separate' and group.recurring_income_id is None
    assert db.session.get(RecurringIncome, recurring.id) is None


def _flag_as_legacy_overrides(recurring):
    """Simulate rows written by the old generator, which flagged forecasts as overrides."""
    for income in Income.query.filter_by(recurring_income_id=recurring.id).all():
        income.is_manual_override = True
    db.session.commit()


def test_delete_recurring_removes_future_forecasts_flagged_as_override(scoped, account):
    recurring = _template(
        start_date=(date.today() - relativedelta(months=2)).replace(day=1).isoformat(),
        deposit_account_id=str(account.id), auto_create_transaction='on',
    )
    IncomeService.generate_missing_income(recurring.id, end_date=date.today() + relativedelta(months=6))
    _flag_as_legacy_overrides(recurring)
    past_ids = {i.id for i in Income.query.filter(Income.pay_date <= date.today()).all()}

    IncomeService.delete_recurring_income(recurring.id)

    assert {i.id for i in Income.query.all()} == past_ids
    assert Transaction.query.filter(Transaction.transaction_date > date.today()).count() == 0


def test_end_job_removes_future_forecasts_flagged_as_override(scoped):
    recurring = _template(start_date=date.today().replace(day=1).isoformat())
    IncomeService.generate_missing_income(recurring.id, end_date=date.today() + relativedelta(months=6))
    _flag_as_legacy_overrides(recurring)

    result = IncomeService.end_job(recurring.id, date.today())

    assert result['kept_paid'] == 0
    assert Income.query.filter(Income.pay_date > date.today()).count() == 0


def test_manual_deduction_templates_generate_forecasts_not_actuals(scoped):
    recurring = _template(use_manual_deductions='on', manual_take_home='2000')
    generated = IncomeService.generate_missing_income(recurring.id, end_date=date(2026, 3, 31))
    assert generated and not any(i.is_manual_override for i in generated)


def test_purge_orphaned_forecasts_preview_then_apply(scoped, account):
    future = date.today() + relativedelta(months=1)
    orphan = IncomeService.create_income_record_manual(
        person='Household', pay_date=future, gross_annual=30000, employer_pension=0,
        employee_pension=0, tax=0, ni=0, take_home=2000, deposit_account_id=account.id,
    )
    paid_orphan = IncomeService.create_income_record_manual(
        person='Household', pay_date=future, gross_annual=30000, employer_pension=0,
        employee_pension=0, tax=0, ni=0, take_home=2000, create_transaction=False,
    )
    paid_orphan.is_paid = True
    one_off = IncomeService.create_income_record(
        person='Household', pay_date=future, gross_annual=30000, create_transaction=False,
    )
    db.session.commit()
    orphan_id, txn_id = orphan.id, orphan.transaction_id

    preview = IncomeService.purge_orphaned_forecasts(dry_run=True)
    assert [g['count'] for g in preview] == [1]
    assert db.session.get(Income, orphan_id) is not None

    IncomeService.purge_orphaned_forecasts(dry_run=False)
    assert db.session.get(Income, orphan_id) is None
    assert db.session.get(Transaction, txn_id) is None
    assert {i.id for i in Income.query.all()} == {paid_orphan.id, one_off.id}
    assert db.session.get(Account, account.id).balance == 0


def test_purge_catches_unflagged_series_but_spares_lone_one_off(scoped):
    base = date.today() + relativedelta(months=1)
    for n in range(4):
        IncomeService.create_income_record(
            person='Household', pay_date=base + relativedelta(months=n), gross_annual=30000,
            source='Old job', create_transaction=False,
        )
    bonus = IncomeService.create_income_record(
        person='Household', pay_date=base, gross_annual=30000, source='Bonus', create_transaction=False,
    )

    preview = IncomeService.purge_orphaned_forecasts(dry_run=True)
    assert [(g['source'], g['count']) for g in preview] == [('Old job', 4)]

    IncomeService.purge_orphaned_forecasts(dry_run=False, family_id=scoped.id + 999)
    assert Income.query.count() == 5  # other household filter touches nothing

    IncomeService.purge_orphaned_forecasts(dry_run=False, family_id=scoped.id)
    assert [i.id for i in Income.query.all()] == [bonus.id]


def _load_override_migration():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / \
        'c4f8a2d6e0b1_clear_legacy_income_forecast_override.py'
    spec = importlib.util.spec_from_file_location('override_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_clears_legacy_flag_only_on_matching_future_forecasts(scoped):
    recurring = _template(
        start_date=(date.today() - relativedelta(months=2)).replace(day=1).isoformat(),
        use_manual_deductions='on', manual_take_home='2000',
    )
    IncomeService.generate_missing_income(recurring.id, end_date=date.today() + relativedelta(months=4))
    _flag_as_legacy_overrides(recurring)
    future = Income.query.filter(Income.pay_date > date.today()).order_by(Income.pay_date).all()
    real_actual = future[0]
    real_actual.take_home = Decimal('2111.11')  # user's own figures: keep the flag
    db.session.commit()

    updated = _load_override_migration().clear_legacy_overrides(db.session.connection())
    db.session.commit()

    assert updated == len(future) - 1
    for income in Income.query.all():
        db.session.refresh(income)
        expected = income.pay_date <= date.today() or income.id == real_actual.id
        assert income.is_manual_override is expected


# --- B10: income category casing -------------------------------------------------

def test_existing_capitalised_salary_category_is_reused(scoped, account):
    legacy = Category(family_id=scoped.id, name='Salary', category_type='Income')
    db.session.add(legacy)
    db.session.commit()
    income = IncomeService.create_income_record(
        person='Household', pay_date=date(2026, 1, 15), gross_annual=30000,
        deposit_account_id=account.id,
    )
    assert income.transaction.category_id == legacy.id
    assert Category.query.filter_by(name='Salary').count() == 1


def test_recurring_form_lists_income_categories_case_insensitively(app, family, user):
    from tests.auth_helpers import login_client

    db.session.add_all([
        Category(family_id=family.id, name='Bonus', category_type='Income', head_budget='Income', sub_budget='Bonus'),
        Category(family_id=family.id, name='Rent', category_type='income', head_budget='Income', sub_budget='Rent'),
    ])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    html = client.get('/income/recurring/add').get_data(as_text=True)
    assert 'Bonus' in html and 'Rent' in html


# --- Privacy takeover --------------------------------------------------------------

def _member(family, name):
    member = User(email=f'{name.lower()}@example.com', name=name, family_id=family.id, role='member')
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()
    return member


def test_member_cannot_make_someone_elses_income_private(scoped, user, monkeypatch):
    emma = _member(scoped, 'Emma')
    recurring = _template(person='Admin User')

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: emma.id)
    with pytest.raises(ValueError, match='Only Admin User'):
        IncomeService.update_recurring_income(recurring.id, {
            'person': 'Admin User', 'start_date': '2026-01-01', 'pay_day': '15',
            'gross_annual': '30000', 'tax_code': '1257L', 'visibility': 'private',
        })


def test_member_cannot_relabel_shared_income_as_theirs_to_hide_it(scoped, user, monkeypatch):
    emma = _member(scoped, 'Emma')
    recurring = _template(person='Admin User')

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: emma.id)
    with pytest.raises(ValueError, match='Only Admin User'):
        IncomeService.update_recurring_income(recurring.id, {
            'person': 'Emma', 'start_date': '2026-01-01', 'pay_day': '15',
            'gross_annual': '30000', 'tax_code': '1257L', 'visibility': 'private',
        })
    db.session.rollback()
    assert db.session.get(RecurringIncome, recurring.id).owner_id is None


def test_earner_can_make_income_private_and_it_cascades(scoped, user):
    recurring = _template(person='Admin User')
    IncomeService.generate_missing_income(recurring.id, end_date=date(2026, 2, 1))

    IncomeService.update_recurring_income(recurring.id, {
        'person': 'Admin User', 'start_date': '2026-01-01', 'pay_day': '15',
        'gross_annual': '30000', 'tax_code': '1257L', 'visibility': 'private', 'is_active': 'on',
    })

    assert recurring.owner_id == user.id
    rows = Income.query.filter_by(recurring_income_id=recurring.id).all()
    assert rows and all(r.owner_id == user.id for r in rows)


def test_household_owner_cannot_make_another_members_income_private(scoped, user):
    _member(scoped, 'Emma')
    with pytest.raises(ValueError):
        _template(person='Emma', visibility='private')


# --- Generation cap / validation ---------------------------------------------------

def test_generation_never_exceeds_horizon(scoped):
    recurring = _template(start_date=date.today().replace(day=1).isoformat())
    generated = IncomeService.generate_missing_income(recurring.id, end_date=date(9999, 1, 1))
    assert generated[-1].pay_date <= date.today() + relativedelta(years=GENERATION_HORIZON_YEARS)


@pytest.mark.parametrize('field,value', [
    ('gross_annual', 'NaN'),
    ('gross_annual', 'Infinity'),
    ('gross_annual', '-1'),
    ('gross_annual', '1e12'),
    ('employee_pension_pct', '150'),
    ('pay_day', '40'),
    ('pay_day', 'x'),
    ('tax_code', 'DROP TABLE'),
    ('start_date', 'not-a-date'),
    ('end_date', '2200-01-01'),
    ('end_date', '2025-01-01'),
])
def test_invalid_template_input_rejected(scoped, field, value):
    with pytest.raises(ValueError):
        _template(**{field: value})


def test_range_operations_validate_dates(scoped):
    recurring = _template()
    with pytest.raises(ValueError):
        IncomeService.delete_income_range(recurring.id, date(2027, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError):
        IncomeService.delete_income_range(recurring.id, date(2026, 1, 1), date(2200, 1, 1))


def test_add_route_shows_validation_message_not_internals(app, family, user):
    from tests.auth_helpers import login_client

    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/income/add', data={
        'person': 'Household', 'pay_date': '2026-01-15', 'gross_annual': 'NaN', 'tax_code': '1257L',
    }, follow_redirects=True)
    assert 'Gross annual income must be a number.' in response.get_data(as_text=True)
    assert Income.query.count() == 0
