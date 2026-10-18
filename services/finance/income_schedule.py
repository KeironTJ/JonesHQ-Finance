"""
Income schedule
===============
Pure helpers (no database access) that turn an income source plus its timeline
into pay dates and the pay terms in force on each date. Used both for the
saved forecasts (IncomeService) and the long-range plan (income projection).

A *source* is anything with RecurringIncome's attributes; *changes* is an
iterable of IncomeChange-like objects.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from services.finance import payroll_calculator
from services.finance.payday_service import PaydayService

STEP_DAYS = {'weekly': 7, 'fortnightly': 14, 'four_weekly': 28}
MAX_AUTO_RISES = 100
CENT = Decimal('0.01')


def frequency_of(source):
    return getattr(source, 'pay_frequency', None) or 'monthly'


def _anchor(source):
    return getattr(source, 'first_pay_date', None) or source.start_date


def monthly_pay_date(pay_day, year, month):
    """Pay date for *pay_day* (0 = last day) in a month, moved back to the
    previous working day if it falls on a weekend or bank holiday."""
    last_day = calendar.monthrange(year, month)[1]
    day = last_day if not pay_day else min(pay_day, last_day)
    return PaydayService.get_previous_working_day(date(year, month, day))


def _nominal_dates(source, start, end):
    """Unadjusted schedule dates that could land in [start, end] once moved
    back to a working day (so the window is padded by a week)."""
    frequency = frequency_of(source)
    if frequency == 'monthly':
        month = start.replace(day=1)
        while month <= end + timedelta(days=7):
            yield month
            month += relativedelta(months=1)
        return
    anchor = _anchor(source)
    if frequency == 'annual':
        k = max(0, start.year - anchor.year - 1)
        while True:
            nominal = anchor + relativedelta(years=k)
            if nominal > end + timedelta(days=7):
                return
            yield nominal
            k += 1
    step = STEP_DAYS[frequency]
    k = max(0, (start - anchor).days // step)
    while True:
        nominal = anchor + timedelta(days=step * k)
        if nominal > end + timedelta(days=7):
            return
        yield nominal
        k += 1


def pay_dates(source, start, end):
    """Sorted pay dates in [start, end] that fall within the source's own
    start/end dates."""
    if end < start:
        return []
    frequency = frequency_of(source)
    result = []
    for nominal in _nominal_dates(source, start, end):
        if frequency == 'monthly':
            paid = monthly_pay_date(source.pay_day, nominal.year, nominal.month)
            earliest_ok = paid >= source.start_date
        else:
            paid = PaydayService.get_previous_working_day(nominal)
            earliest_ok = nominal >= source.start_date
        if not earliest_ok or not start <= paid <= end:
            continue
        if source.end_date and paid > source.end_date:
            continue
        result.append(paid)
    return sorted(set(result))


def previous_pay_date(source, pay_date):
    """The scheduled pay date before *pay_date*, or None if it is the first."""
    earlier = pay_dates(source, pay_date - timedelta(days=400), pay_date - timedelta(days=1))
    return earlier[-1] if earlier else None


def rise_dates(source, until):
    """Dates of the automatic yearly rise up to and including *until*."""
    percent = getattr(source, 'annual_increase_percent', None)
    first = getattr(source, 'annual_increase_start', None)
    if not percent or not first:
        return []
    dates = []
    for k in range(MAX_AUTO_RISES):
        rise = first + relativedelta(years=k)
        if rise > until:
            break
        dates.append(rise)
    return dates


@dataclass
class PayTerms:
    gross_annual: Decimal
    tax_code: str
    employee_pension_pct: Decimal
    employer_pension_pct: Decimal
    bonus: Decimal = Decimal('0')
    bonus_pensionable: bool = False


def terms_for(source, changes, pay_date, previous=None):
    """
    Terms in force on *pay_date*: the source's starting terms with every
    automatic rise and timeline change dated on or before it applied in date
    order (explicit changes after an automatic rise on the same day). Bonuses
    dated after *previous* (the prior pay date) and up to *pay_date* are paid.
    """
    gross = Decimal(str(source.gross_annual_income or 0))
    tax_code = source.tax_code or '1257L'
    employee_pct = Decimal(str(source.employee_pension_percent or 0))
    employer_pct = Decimal(str(source.employer_pension_percent or 0))
    auto_pct = Decimal(str(getattr(source, 'annual_increase_percent', None) or 0))

    events = [(when, 0, None) for when in rise_dates(source, pay_date)]
    bonus = Decimal('0')
    bonus_pensionable = False
    for change in changes:
        if change.effective_date > pay_date:
            continue
        if change.change_type == 'bonus':
            if previous is None or change.effective_date > previous:
                bonus += Decimal(str(change.amount or 0))
                bonus_pensionable = bonus_pensionable or bool(change.bonus_pensionable)
            continue
        events.append((change.effective_date, 1, change))
    events.sort(key=lambda event: (event[0], event[1], getattr(event[2], 'id', 0) or 0))

    for _, _, change in events:
        if change is None:
            gross = (gross * (1 + auto_pct / 100)).quantize(CENT)
        elif change.change_type == 'salary' and change.amount is not None:
            gross = Decimal(str(change.amount))
        elif change.change_type == 'percent_rise' and change.percent is not None:
            gross = (gross * (1 + Decimal(str(change.percent)) / 100)).quantize(CENT)
        elif change.change_type == 'tax_code' and change.tax_code:
            tax_code = change.tax_code
        elif change.change_type == 'pension':
            if change.employee_pension_percent is not None:
                employee_pct = Decimal(str(change.employee_pension_percent))
            if change.employer_pension_percent is not None:
                employer_pct = Decimal(str(change.employer_pension_percent))
    return PayTerms(gross, tax_code, employee_pct, employer_pct, bonus.quantize(CENT), bonus_pensionable)


def estimate(source, terms, pay_date, settings):
    """Payslip estimate for *pay_date* under *terms*."""
    return payroll_calculator.calculate_payslip(
        terms.gross_annual, terms.tax_code, settings, pay_date,
        frequency=frequency_of(source),
        income_type=getattr(source, 'income_type', None) or 'employment',
        employee_pension_pct=terms.employee_pension_pct,
        employer_pension_pct=terms.employer_pension_pct,
        pension_scheme=getattr(source, 'pension_scheme', None) or payroll_calculator.DEFAULT_PENSION_SCHEME,
        avc=source.avc or 0,
        other=source.other_deductions or 0,
        student_loan_plans=getattr(source, 'student_loan_plans', None) or (),
        bonus=terms.bonus,
        bonus_pensionable=terms.bonus_pensionable,
        set_aside_pct=getattr(source, 'set_aside_percent', None) or 0,
    )
