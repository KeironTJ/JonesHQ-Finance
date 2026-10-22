"""Income redesign: schedules, timeline terms, forecast refresh, plan and pages."""
import time
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from dateutil.relativedelta import relativedelta
from werkzeug.exceptions import NotFound

from extensions import db
from models.income import Income
from models.income_change import IncomeChange
from models.recurring_income import RecurringIncome
from models.users import User
from services.finance import income_schedule, payroll_calculator
from services.finance.income_projection_service import IncomeProjectionService
from services.finance.income_service import IncomeService
from services.finance.income_forecast_service import IncomeForecastService


@pytest.fixture
def scoped(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    return family


@pytest.fixture
def client(app, user, scoped):
    from tests.auth_helpers import login_client
    c = app.test_client()
    login_client(c, user.id)
    return c


def _source(**overrides):
    data = {
        'person': 'Household',
        'source': 'Acme',
        'start_date': (date.today().replace(day=1) - relativedelta(months=3)).isoformat(),
        'end_date': '',
        'pay_day': '15',
        'gross_annual': '36000',
        'employer_pension_pct': '3',
        'employee_pension_pct': '5',
        'tax_code': '1257L',
        'deposit_account_id': '',
        'category_id': '',
    }
    data.update(overrides)
    return IncomeService.save_income_source(data)


def _ns(**kw):
    base = dict(pay_frequency='monthly', pay_day=15, first_pay_date=None, start_date=date(2026, 1, 1),
                end_date=None, gross_annual_income=Decimal('30000'), tax_code='1257L',
                employee_pension_percent=0, employer_pension_percent=0,
                annual_increase_percent=None, annual_increase_start=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _change(change_type, when, id=1, **kw):
    return SimpleNamespace(change_type=change_type, effective_date=when, id=id, amount=kw.get('amount'),
                           percent=kw.get('percent'), tax_code=kw.get('tax_code'),
                           employee_pension_percent=kw.get('employee'), employer_pension_percent=kw.get('employer'),
                           bonus_pensionable=kw.get('pensionable', False))


# --- Schedules ---------------------------------------------------------------

@pytest.mark.parametrize('frequency, expected', [
    ('weekly', [2, 9, 16, 23, 30]),
    ('fortnightly', [2, 16, 30]),
    ('four_weekly', [2, 30]),
])
def test_repeating_schedules_step_from_first_pay_date(frequency, expected):
    src = _ns(pay_frequency=frequency, first_pay_date=date(2026, 1, 2), start_date=date(2026, 1, 1))
    dates = income_schedule.pay_dates(src, date(2026, 1, 1), date(2026, 1, 31))
    assert [d.day for d in dates] == expected


def test_annual_schedule_uses_anniversary():
    src = _ns(pay_frequency='annual', first_pay_date=date(2026, 3, 10), start_date=date(2026, 3, 10))
    assert income_schedule.pay_dates(src, date(2026, 1, 1), date(2028, 12, 31)) == [
        date(2026, 3, 10), date(2027, 3, 10), date(2028, 3, 10)]


def test_monthly_pay_day_on_weekend_moves_earlier():
    src = _ns(pay_day=25)
    # 25 Oct 2026 is a Sunday.
    assert income_schedule.pay_dates(src, date(2026, 10, 1), date(2026, 10, 31)) == [date(2026, 10, 23)]


def test_schedule_respects_end_date():
    src = _ns(pay_frequency='weekly', first_pay_date=date(2026, 1, 2), end_date=date(2026, 1, 20))
    assert income_schedule.pay_dates(src, date(2026, 1, 1), date(2026, 2, 28))[-1] == date(2026, 1, 16)


# --- Terms from the timeline ---------------------------------------------------

def test_auto_rise_applies_before_same_day_explicit_change_then_salary_reset():
    src = _ns(annual_increase_percent=Decimal('3'), annual_increase_start=date(2027, 4, 1))
    changes = [
        _change('percent_rise', date(2027, 4, 1), id=1, percent=Decimal('10')),
        _change('salary', date(2028, 1, 1), id=2, amount=Decimal('40000')),
    ]
    assert income_schedule.terms_for(src, changes, date(2027, 3, 15)).gross_annual == Decimal('30000')
    assert income_schedule.terms_for(src, changes, date(2027, 4, 15)).gross_annual == Decimal('33990.00')
    assert income_schedule.terms_for(src, changes, date(2028, 1, 15)).gross_annual == Decimal('40000')
    assert income_schedule.terms_for(src, changes, date(2028, 4, 15)).gross_annual == Decimal('41200.00')


def test_bonus_paid_once_on_next_pay_date():
    src = _ns()
    changes = [_change('bonus', date(2027, 6, 10), amount=Decimal('1000'), pensionable=True)]
    june = income_schedule.terms_for(src, changes, date(2027, 6, 15), previous=date(2027, 5, 14))
    july = income_schedule.terms_for(src, changes, date(2027, 7, 15), previous=date(2027, 6, 15))
    assert june.bonus == Decimal('1000.00') and june.bonus_pensionable
    assert july.bonus == 0


def test_tax_code_and_pension_changes():
    src = _ns(employee_pension_percent=5, employer_pension_percent=3)
    changes = [
        _change('tax_code', date(2027, 4, 6), id=1, tax_code='S1257L'),
        _change('pension', date(2027, 5, 1), id=2, employee=Decimal('8')),
    ]
    terms = income_schedule.terms_for(src, changes, date(2027, 5, 15))
    assert terms.tax_code == 'S1257L'
    assert terms.employee_pension_pct == Decimal('8') and terms.employer_pension_pct == Decimal('3')


# --- Forecast refresh ------------------------------------------------------------

def _future(recurring):
    return Income.query.filter(Income.recurring_income_id == recurring.id,
                               Income.pay_date > date.today()).order_by(Income.pay_date).all()


def test_new_source_forecasts_five_years_by_default(scoped):
    recurring = _source()
    future = _future(recurring)
    assert future
    assert future[-1].pay_date <= date.today() + relativedelta(years=5)
    assert future[-1].pay_date >= date.today() + relativedelta(years=5, months=-1)


def test_forecast_years_setting_extends_and_shortens(scoped):
    recurring = _source()
    IncomeForecastService.set_forecast_years(2)
    IncomeForecastService.refresh_all_forecasts()
    assert _future(recurring)[-1].pay_date <= date.today() + relativedelta(years=2)

    IncomeForecastService.set_forecast_years(8)
    IncomeForecastService.refresh_all_forecasts()
    assert _future(recurring)[-1].pay_date >= date.today() + relativedelta(years=8, months=-1)
    assert IncomeForecastService.forecast_years() == 8


@pytest.mark.parametrize('value', ['0', '11', 'abc', None])
def test_forecast_years_validation(scoped, value):
    with pytest.raises(ValueError):
        IncomeForecastService.set_forecast_years(value)


def test_forecast_years_is_per_household(scoped, monkeypatch):
    from models.family import Family
    IncomeForecastService.set_forecast_years(3)
    other = Family(name='Other')
    db.session.add(other)
    db.session.commit()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: other.id)
    assert IncomeForecastService.forecast_years() == 5


def test_pay_rise_reprices_unsettled_forecasts_only(scoped):
    recurring = _source()
    future = _future(recurring)
    paid, actual = future[2], future[3]
    paid.is_paid = True
    actual.is_manual_override = True
    actual.take_home = Decimal('1.23')
    db.session.commit()
    before = {i.id: Decimal(str(i.gross_monthly_income)) for i in future}
    count = len(future)

    IncomeService.add_income_change(recurring.id, {
        'change_type': 'percent_rise', 'effective_date': date.today().isoformat(), 'percent': '10'})

    after = _future(recurring)
    assert len(after) == count
    by_id = {i.id: i for i in after}
    assert Decimal(str(by_id[paid.id].gross_monthly_income)) == before[paid.id]
    assert Decimal(str(by_id[actual.id].take_home)) == Decimal('1.23')
    other = after[0] if after[0].id not in (paid.id, actual.id) else after[-1]
    assert Decimal(str(other.gross_monthly_income)) == (before[other.id] * Decimal('1.1')).quantize(Decimal('0.01'))


def test_bonus_change_adds_to_one_payslip_and_removal_reverts(scoped):
    recurring = _source()
    target = _future(recurring)[1]
    change = IncomeService.add_income_change(recurring.id, {
        'change_type': 'bonus', 'effective_date': (target.pay_date - timedelta(days=1)).isoformat(), 'amount': '2000'})
    bonused = [i for i in _future(recurring) if i.bonus]
    assert [i.pay_date for i in bonused] == [target.pay_date]
    assert Decimal(str(bonused[0].bonus)) == Decimal('2000')

    IncomeService.delete_income_change(change.id)
    assert not [i for i in _future(recurring) if i.bonus]


def test_earlier_end_date_removes_later_forecasts_but_keeps_settled(scoped):
    recurring = _source()
    future = _future(recurring)
    keeper = future[10]
    keeper.is_paid = True
    db.session.commit()
    end = date.today() + relativedelta(months=6)
    IncomeService.save_income_source({
        'person': 'Household', 'source': 'Acme', 'start_date': recurring.start_date.isoformat(),
        'end_date': end.isoformat(), 'pay_day': '15', 'gross_annual': '36000', 'tax_code': '1257L',
        'is_active': 'on', 'auto_create_transaction': 'on',
    }, recurring_id=recurring.id)
    remaining = _future(recurring)
    assert all(i.pay_date <= end or i.id == keeper.id for i in remaining)
    assert keeper.id in {i.id for i in remaining}


def test_switching_to_weekly_redates_forecasts(scoped):
    recurring = _source()
    first = date.today() + timedelta(days=(4 - date.today().weekday()) % 7 or 7)
    IncomeService.save_income_source({
        'person': 'Household', 'source': 'Acme', 'start_date': recurring.start_date.isoformat(),
        'pay_frequency': 'weekly', 'first_pay_date': first.isoformat(), 'gross_annual': '36000',
        'tax_code': '1257L', 'is_active': 'on',
    }, recurring_id=recurring.id)
    future = _future(recurring)
    assert len(future) > 90
    assert all(i.pay_frequency == 'weekly' for i in future)
    gaps = {(b.pay_date - a.pay_date).days for a, b in zip(future, future[1:])}
    assert gaps <= {7, 6, 8, 5, 9}


def test_pausing_source_removes_unsettled_forecasts(scoped):
    recurring = _source()
    IncomeService.save_income_source({
        'person': 'Household', 'source': 'Acme', 'start_date': recurring.start_date.isoformat(),
        'pay_day': '15', 'gross_annual': '36000', 'tax_code': '1257L',
    }, recurring_id=recurring.id)
    assert _future(recurring) == []


# --- Timeline validation & privacy --------------------------------------------------

@pytest.mark.parametrize('data, message', [
    ({'change_type': 'percent_rise', 'percent': '0'}, 'cannot be zero'),
    ({'change_type': 'salary', 'amount': '-5'}, None),
    ({'change_type': 'bonus'}, None),
    ({'change_type': 'pension'}, 'pension %'),
    ({'change_type': 'nonsense'}, None),
])
def test_invalid_changes_rejected(scoped, data, message):
    recurring = _source()
    data = {'effective_date': date.today().isoformat(), **data}
    with pytest.raises(ValueError, match=message):
        IncomeService.add_income_change(recurring.id, data)
    db.session.rollback()
    assert IncomeChange.query.count() == 0


def test_change_before_start_rejected(scoped):
    recurring = _source()
    with pytest.raises(ValueError, match='before the income starts'):
        IncomeService.add_income_change(recurring.id, {
            'change_type': 'tax_code', 'tax_code': 'BR',
            'effective_date': (recurring.start_date - timedelta(days=1)).isoformat()})


def test_other_members_private_timeline_is_hidden(scoped, family, user, monkeypatch):
    other = User(email='other@example.com', name='Other', family_id=family.id, role='member')
    other.set_password('TestPass1!')
    db.session.add(other)
    db.session.commit()
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: other.id)
    recurring = _source(person='Other', visibility='private')
    change = IncomeService.add_income_change(recurring.id, {
        'change_type': 'tax_code', 'tax_code': 'BR', 'effective_date': date.today().isoformat()})
    assert recurring.owner_id == other.id

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    with pytest.raises(NotFound):
        IncomeService.delete_income_change(change.id)
    with pytest.raises(NotFound):
        IncomeService.add_income_change(recurring.id, {
            'change_type': 'tax_code', 'tax_code': 'BR', 'effective_date': date.today().isoformat()})


def test_deleting_source_deletes_its_timeline(scoped):
    recurring = _source()
    IncomeService.add_income_change(recurring.id, {
        'change_type': 'tax_code', 'tax_code': 'BR', 'effective_date': date.today().isoformat()})
    IncomeService.delete_recurring_income(recurring.id)
    assert IncomeChange.query.count() == 0


# --- Plan ------------------------------------------------------------------------

def test_plan_uses_saved_rows_then_projects_until_end_date(scoped):
    end = date.today() + relativedelta(years=4)
    recurring = _source(end_date=end.isoformat(), annual_increase_percent='3',
                        annual_increase_start=(date.today() + relativedelta(months=1)).isoformat())
    plan = IncomeProjectionService.build_plan(until_year=payroll_calculator.tax_year_start(date.today()) + 6)

    first = plan['years'][0]
    year_start = date(first['start'], 4, 6)
    saved = Income.query.filter(Income.recurring_income_id == recurring.id,
                                Income.pay_date >= year_start,
                                Income.pay_date < year_start + relativedelta(years=1)).all()
    assert first['totals']['take_home'] == sum(Decimal(str(i.take_home)) for i in saved)

    by_year = {y['start']: y['totals']['gross'] for y in plan['years']}
    end_year = payroll_calculator.tax_year_start(end)
    assert by_year[end_year + 1] == 0
    full_years = [y for y in sorted(by_year) if first['start'] < y < end_year]
    assert all(by_year[b] > by_year[a] for a, b in zip(full_years, full_years[1:]))


def test_plan_handles_fifty_years_of_weekly_pay_quickly(scoped):
    _source(pay_frequency='weekly', first_pay_date=date.today().isoformat(),
            start_date=date.today().isoformat(), annual_increase_percent='2',
            annual_increase_start=(date.today() + relativedelta(years=1)).isoformat())
    started = time.perf_counter()
    plan = IncomeProjectionService.build_plan(until_year=10_000)
    assert time.perf_counter() - started < 20
    assert len(plan['years']) == 51
    assert plan['years'][-1]['totals']['gross'] > plan['years'][1]['totals']['gross']


def test_plan_rejects_garbage_year(scoped):
    with pytest.raises(ValueError):
        IncomeProjectionService.build_plan(until_year='abc')


def test_plan_counts_paid_history_of_closed_sources_without_projecting(scoped):
    year_start = date(payroll_calculator.tax_year_start(date.today()), 4, 6)
    old = _source(source='Old job', start_date=year_start.isoformat())
    past = Income.query.filter(Income.recurring_income_id == old.id, Income.pay_date <= date.today()).all()
    for income in past:
        income.is_paid = True
    old.is_active = False
    db.session.commit()
    IncomeForecastService.refresh_forecasts(old.id)

    plan = IncomeProjectionService.build_plan()
    expected = sum(Decimal(str(i.take_home)) for i in past)
    assert plan['years'][0]['totals']['take_home'] == expected
    assert all(y['totals']['gross'] == 0 for y in plan['years'][1:])


def _set_retirement(years_from_now, person='Household', age=67):
    dob = date.today() + relativedelta(years=years_from_now - age)
    return IncomeProjectionService.set_retirement(
        person, {'date_of_birth': dob.isoformat(), 'retirement_age': str(age)})


def test_plan_stops_work_income_at_retirement_and_warns(scoped):
    _source()
    _source(source='State', income_type='rental', set_aside_percent='20')
    info = _set_retirement(8)
    plan = IncomeProjectionService.build_plan()

    retire_year = payroll_calculator.tax_year_start(info['date'])
    assert plan['until_year'] == retire_year + 1
    last = plan['years'][-1]
    assert last['by_type'].get('employment') is None
    assert last['by_type']['rental']['gross'] > 0
    assert next(y for y in plan['years'] if y['start'] == retire_year)['retiring'] == ['Household']
    assert any('no pension income source' in w for w in plan['warnings'])
    # Forecast rows are only saved 5 years ahead, so the job's end date isn't the issue here.
    assert any('stopped at' in w for w in plan['warnings'])


def test_saved_forecasts_after_retirement_are_dropped_but_paid_rows_kept(scoped):
    recurring = _source()
    info = _set_retirement(2)
    later = Income.query.filter(Income.recurring_income_id == recurring.id,
                                Income.pay_date > info['date']).order_by(Income.pay_date).all()
    assert later
    later[0].is_paid = True
    db.session.commit()
    plan = IncomeProjectionService.build_plan(until_year=payroll_calculator.tax_year_start(date.today()) + 4)
    employment = [y['by_type'].get('employment', {}).get('gross', 0) for y in plan['years']]
    after = [y for y in plan['years'] if y['start'] > payroll_calculator.tax_year_start(later[0].pay_date)]
    assert all('employment' not in y['by_type'] for y in after)
    assert sum(employment) > 0


@pytest.mark.parametrize('data, message', [
    ({'date_of_birth': 'nope'}, 'valid date'),
    ({'date_of_birth': '1900-01-01'}, '16 to 100'),
    ({'date_of_birth': '1980-01-01', 'retirement_age': '40'}, 'between'),
    ({'date_of_birth': '1980-01-01', 'retirement_age': 'x'}, 'whole-number'),
])
def test_retirement_validation(scoped, data, message):
    _source()
    with pytest.raises(ValueError, match=message):
        IncomeProjectionService.set_retirement('Household', data)


def test_retirement_only_for_people_with_income(scoped):
    with pytest.raises(ValueError):
        IncomeProjectionService.set_retirement('Nobody', {'date_of_birth': '1980-01-01'})


def test_retirement_shared_with_pension_planner_and_clearable(scoped):
    from services.planning.pension_service import PensionService
    _source()
    _set_retirement(10)
    assert PensionService.get_person_age('Household') == 57
    IncomeProjectionService.set_retirement('Household', {'date_of_birth': ''})
    assert IncomeProjectionService.retirement_for('Household') is None


def test_2026_tables_are_built_in(scoped):
    estimate = payroll_calculator.calculate_payslip(
        Decimal('40000'), 'S1257L', IncomeService.get_tax_settings_for_date(date(2026, 6, 1)),
        date(2026, 6, 1), student_loan_plans=['plan_2'])
    assert not any('assumed unchanged' in w or 'latest known' in w for w in estimate.warnings)
    # Plan 2 2026-27 threshold £29,385: (40000 - 29385) / 12 * 9% ≈ £79.61
    assert Decimal('79') <= estimate.student_loan <= Decimal('80')


# --- Pages -----------------------------------------------------------------------

def test_income_pages_render(client, scoped):
    recurring = _source()
    IncomeService.add_income_change(recurring.id, {
        'change_type': 'bonus', 'amount': '500', 'effective_date': date.today().isoformat()})
    for url in ('/income', '/income/recurring', f'/income/recurring/{recurring.id}',
                f'/income/recurring/{recurring.id}/edit', '/income/recurring/add',
                '/income/plan', '/income/plan?person=Household&until=2040'):
        response = client.get(url)
        assert response.status_code == 200, url


def test_add_weekly_source_via_form_then_timeline_routes(client, scoped):
    response = client.post('/income/recurring/add', data={
        'person': 'Household', 'source': 'Shop', 'income_type': 'employment', 'pay_frequency': 'weekly',
        'start_date': date.today().isoformat(), 'first_pay_date': date.today().isoformat(),
        'gross_annual': '26000', 'tax_code': '1257L', 'student_loan_plans': ['plan_2'],
        'pension_scheme': 'net_pay', 'auto_create_transaction': 'on',
    })
    recurring = RecurringIncome.query.filter_by(source='Shop').one()
    assert response.status_code == 302 and response.location.endswith(f'/income/recurring/{recurring.id}')
    assert recurring.pay_frequency == 'weekly' and recurring.student_loan_plans == 'plan_2'
    assert Income.query.filter_by(recurring_income_id=recurring.id).count() > 90

    client.post(f'/income/recurring/{recurring.id}/changes', data={
        'change_type': 'salary', 'amount': '30000', 'effective_date': date.today().isoformat()})
    change = IncomeChange.query.one()
    page = client.get(f'/income/recurring/{recurring.id}').get_data(as_text=True)
    assert 'New salary' in page and '£30,000.00 a year' in page

    client.post(f'/income/changes/{change.id}/delete')
    assert IncomeChange.query.count() == 0


def test_preview_supports_frequency_and_student_loan(client):
    response = client.post('/income/calculate-preview', json={
        'gross_annual': '52000', 'tax_code': '1257L', 'pay_frequency': 'weekly',
        'student_loan_plans': ['plan_2'], 'employee_pension_pct': '5',
    })
    body = response.get_json()
    assert body['success'] and body['frequency'] == 'weekly' and body['student_loan'] > 0
    assert 900 < body['gross_period'] < 1100


def test_refresh_all_route(client, scoped):
    _source()
    response = client.post('/income/refresh-forecasts', follow_redirects=True)
    assert 'Forecasts refreshed' in response.get_data(as_text=True)


def test_refresh_route_saves_forecast_years(client, scoped):
    _source()
    client.post('/income/refresh-forecasts', data={'forecast_years': '7', 'next': 'sources'})
    assert IncomeForecastService.forecast_years() == 7
    response = client.post('/income/refresh-forecasts', data={'forecast_years': '99'}, follow_redirects=True)
    assert 'from 1 to 10 years' in response.get_data(as_text=True)
    assert IncomeForecastService.forecast_years() == 7


def test_retirement_route(client, scoped):
    _source()
    response = client.post('/income/plan/retirement', data={
        'person': 'Household', 'date_of_birth': '1980-05-01', 'retirement_age': '66'}, follow_redirects=True)
    assert 'retires on 01 May 2046' in response.get_data(as_text=True)
    page = client.get('/income/plan').get_data(as_text=True)
    assert 'Household retires' in page and 'value="1980-05-01"' in page


# --- Household member link ---------------------------------------------------

def _member(family, name, member_name=None, email=None):
    member = User(email=email or f'{name.lower().replace(" ", ".")}@example.com', name=name,
                  member_name=member_name, family_id=family.id, role='member')
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()
    return member


def test_source_and_its_payslips_link_to_the_member(scoped, family, user):
    partner = _member(family, 'Partner Account', member_name='Sam')
    recurring = _source(person='sam')
    assert recurring.member_id == partner.id
    payslips = Income.query.filter_by(recurring_income_id=recurring.id).all()
    assert payslips and {p.member_id for p in payslips} == {partner.id}

    household = _source(person='Household')
    assert household.member_id is None


def test_ambiguous_names_are_not_linked(scoped, family, user):
    _member(family, 'Alex One', member_name='Alex')
    _member(family, 'Alex Two', member_name='Alex')
    assert _source(person='Alex').member_id is None


def test_one_off_and_edited_payslips_follow_the_person(scoped, family, user):
    partner = _member(family, 'Sam')
    one_off = IncomeService.create_one_off_income({
        'person': 'Sam', 'pay_date': date.today().isoformat(), 'gross_annual': '12000', 'tax_code': '1257L',
    })
    assert one_off.member_id == partner.id
    IncomeService.update_income_record(one_off.id, {
        'person': 'Admin User', 'pay_date': date.today().isoformat(), 'gross_annual': '12000', 'tax_code': '1257L',
    })
    assert db.session.get(Income, one_off.id).member_id == user.id


def test_renaming_a_member_renames_their_income(scoped, family, user):
    from services.household.family_service import FamilyService

    partner = _member(family, 'Sam Smith', member_name='Sam')
    recurring = _source(person='Sam')
    legacy = IncomeService.create_one_off_income({
        'person': 'Household', 'pay_date': date.today().isoformat(), 'gross_annual': '1000', 'tax_code': '1257L',
    })
    db.session.execute(Income.__table__.update().where(Income.id == legacy.id)
                       .values(person='Sam', member_id=None))
    db.session.commit()

    FamilyService.update_member(partner.id, family.id, user.id, 'member', 'Samantha', [])

    db.session.expire_all()
    assert db.session.get(RecurringIncome, recurring.id).person == 'Samantha'
    assert {p.person for p in Income.query.filter_by(member_id=partner.id).all()} == {'Samantha'}
    # Unlinked rows recorded under the old name are picked up too.
    assert db.session.get(Income, legacy.id).member_id == partner.id


def test_joining_household_links_income_recorded_under_invited_name(scoped, family, user, monkeypatch):
    from datetime import datetime
    from models.family import FamilyInvite
    from services.household.family_service import FamilyService

    recurring = _source(person='Jo')
    assert recurring.member_id is None
    joiner = User(email='jo@example.com', name='Joanne')
    joiner.set_password('TestPass1!')
    db.session.add(joiner)
    invite = FamilyInvite(family_id=family.id, member_name='Jo', role='member', token='tok-jo',
                          created_by_id=user.id, expires_at=datetime.now() + timedelta(days=2))
    db.session.add(invite)
    db.session.commit()

    monkeypatch.setattr('services.household.family_service.get_current_user_id', lambda: joiner.id)
    FamilyService.join_existing(joiner, {'token': 'tok-jo'})
    db.session.expire_all()

    assert db.session.get(RecurringIncome, recurring.id).member_id == joiner.id


def test_removing_a_member_unlinks_but_keeps_their_income(scoped, family, user):
    from services.household.family_service import FamilyService

    partner = _member(family, 'Sam')
    recurring = _source(person='Sam')
    FamilyService.remove_member(partner.id, family.id, user.id)
    db.session.expire_all()
    kept = db.session.get(RecurringIncome, recurring.id)
    assert kept.person == 'Sam' and kept.member_id is None
    assert Income.query.filter_by(member_id=partner.id).count() == 0


def test_only_the_linked_member_can_make_their_income_private(scoped, family, user):
    partner = _member(family, 'Partner Account', member_name='Sam')
    with pytest.raises(ValueError, match='Only Sam'):
        _source(person='Sam', visibility='private')
    assert _source(person='Admin User', visibility='private').owner_id == user.id
    assert partner.id != user.id
