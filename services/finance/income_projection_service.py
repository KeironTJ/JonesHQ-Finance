"""
Income plan
===========
Long-range, read-only projection of household income per UK tax year, up to
retirement (each source's end date) or a chosen year. Saved Income rows are
used where they exist (so actual payslips count); beyond them each source's
schedule, timeline and yearly rise are projected with the payroll calculator.

Assumes today's tax bands, NI and student loan thresholds stay frozen.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_

from models.income import Income
from models.income_change import IncomeChange
from models.recurring_income import RecurringIncome
from services.finance import income_schedule, payroll_calculator
from services.finance.income_forecast_service import IncomeForecastService
from services.household.member_identity_service import MemberIdentityService, UNSPECIFIED_MEMBER
from services.planning.retirement_service import RetirementService
from utils.db_helpers import family_query

MAX_PLAN_YEARS = 50
DEFAULT_PLAN_YEARS = 10
# Income that stops at retirement; pensions, rental, benefits carry on.
WORK_INCOME_TYPES = {'employment', 'self_employed'}
PENSION_INCOME_TYPES = {'private_pension', 'state_pension'}
FIELDS = ('gross', 'income_tax', 'national_insurance', 'student_loan',
          'employee_pension', 'employer_pension', 'avc', 'take_home')
ZERO = Decimal('0')


def _empty():
    return {field: ZERO for field in FIELDS}


def _add(target, values):
    for field in FIELDS:
        target[field] += values[field]


def _from_row(income):
    def d(value):
        return Decimal(str(value or 0))
    return {
        'gross': d(income.gross_monthly_income),
        'income_tax': d(income.income_tax),
        'national_insurance': d(income.national_insurance),
        'student_loan': d(income.student_loan),
        'employee_pension': d(income.employee_pension_amount),
        'employer_pension': d(income.employer_pension_amount),
        'avc': d(income.avc),
        'take_home': d(income.take_home),
    }


def _from_estimate(estimate):
    return {
        'gross': estimate.gross_period,
        'income_tax': estimate.income_tax,
        'national_insurance': estimate.national_insurance,
        'student_loan': estimate.student_loan,
        'employee_pension': estimate.employee_pension,
        'employer_pension': estimate.employer_pension,
        'avc': estimate.avc,
        'take_home': estimate.take_home,
    }


def _is_stale_table_warning(warning):
    return 'assumed unchanged' in warning or 'latest known bands' in warning


def _from_fixed(source):
    def d(value):
        return Decimal(str(value or 0))
    return {
        'gross': (d(source.gross_annual_income) / 12).quantize(Decimal('0.01')),
        'income_tax': d(source.manual_tax_monthly),
        'national_insurance': d(source.manual_ni_monthly),
        'student_loan': ZERO,
        'employee_pension': d(source.manual_employee_pension),
        'employer_pension': d(source.manual_employer_pension),
        'avc': d(source.avc),
        'take_home': d(source.manual_take_home),
    }


class IncomeProjectionService:

    @staticmethod
    def retirement_for(person, member_id=UNSPECIFIED_MEMBER):
        """{'date_of_birth', 'age', 'date'} for a person, or None when no date of birth is set."""
        return RetirementService.profile(person, member_id)

    @staticmethod
    def set_retirement(person, data, today=None):
        """Save (or clear, with a blank date of birth) a person's date of birth and retirement age."""
        person, member_id = MemberIdentityService.resolve(dict(data, person=person))
        query = family_query(RecurringIncome)
        query = query.filter_by(member_id=member_id) if member_id else query.filter_by(person=person)
        if not query.first():
            raise ValueError('Choose a person who has an income source.')
        return RetirementService.save(person, data, member_id, today)

    @staticmethod
    def source_snapshot(source, today=None):
        """Current terms, next saved payslip and timeline for one source."""
        today = today or date.today()
        changes = family_query(IncomeChange).filter(
            IncomeChange.recurring_income_id == source.id
        ).order_by(IncomeChange.effective_date, IncomeChange.id).all()
        terms = income_schedule.terms_for(source, changes, max(today, source.start_date))
        next_payslip = family_query(Income).filter(
            Income.recurring_income_id == source.id, Income.pay_date >= today,
        ).order_by(Income.pay_date).first()
        regular = family_query(Income).filter(
            Income.recurring_income_id == source.id, Income.pay_date >= today,
            or_(Income.bonus.is_(None), Income.bonus == 0),
        ).order_by(Income.pay_date).first()
        periods = payroll_calculator.PAY_FREQUENCIES.get(income_schedule.frequency_of(source), 12)
        monthly_take_home = None
        if regular is not None:
            base = Decimal(str(regular.take_home or 0))
            monthly_take_home = (base * periods / 12).quantize(Decimal('0.01'))
        return {
            'source': source,
            'terms': terms,
            'changes': changes,
            'upcoming_changes': [c for c in changes if c.effective_date > today],
            'next_payslip': next_payslip,
            'monthly_take_home': monthly_take_home,
            'ended': bool(source.end_date and source.end_date < today),
        }

    @staticmethod
    def default_until_year(sources, today=None, retirement_dates=()):
        """Show up to the last retirement (plus that first retired year) when known,
        otherwise to the last end date, or 10 years for open-ended income."""
        today = today or date.today()
        first = payroll_calculator.tax_year_start(today)
        future_retirements = [d for d in retirement_dates if d > today]
        if future_retirements:
            latest = payroll_calculator.tax_year_start(max(future_retirements)) + 1
            return min(max(latest, first), first + MAX_PLAN_YEARS)
        ends = [s.end_date for s in sources if s.end_date and s.end_date > today]
        if not ends or any(s.end_date is None for s in sources):
            latest = max([first + DEFAULT_PLAN_YEARS] + [payroll_calculator.tax_year_start(e) for e in ends])
        else:
            latest = payroll_calculator.tax_year_start(max(ends))
        return min(latest, first + MAX_PLAN_YEARS)

    @staticmethod
    def payslips(source, start, end, settings_for, changes=None, saved=None):
        """
        (pay_date, values, is_saved) for a source between *start* and *end*.
        *saved* rows win for their dates; the rest are projected.
        """
        saved = saved or []
        results = [(row.pay_date, _from_row(row), True) for row in saved]
        last_saved = max((row.pay_date for row in saved), default=None)
        project_from = max(start, last_saved + timedelta(days=1)) if last_saved else start
        dates = income_schedule.pay_dates(source, project_from, end)
        if not dates:
            return results, []
        warnings = set()
        if IncomeForecastService.uses_fixed_figures(source):
            fixed = _from_fixed(source)
            results.extend((d, dict(fixed), False) for d in dates)
            return results, ['Fixed payslip figures are used for this source; pay rises are ignored.']
        changes = changes if changes is not None else []
        previous = income_schedule.previous_pay_date(source, dates[0])
        current_year = payroll_calculator.tax_year_start(date.today())
        for pay_date in dates:
            terms = income_schedule.terms_for(source, changes, pay_date, previous)
            estimate = income_schedule.estimate(source, terms, pay_date, settings_for(pay_date))
            if payroll_calculator.tax_year_start(pay_date) > current_year:
                # Future thresholds are assumed frozen (stated on the plan), so don't repeat it per year.
                warnings.update(w for w in estimate.warnings if not _is_stale_table_warning(w))
            else:
                warnings.update(estimate.warnings)
            results.append((pay_date, _from_estimate(estimate), False))
            previous = pay_date
        return results, sorted(warnings)

    @staticmethod
    def build_plan(until_year=None, person=None, today=None):
        from services.finance.income_service import IncomeService

        today = today or date.today()
        first_year = payroll_calculator.tax_year_start(today)
        sources = family_query(RecurringIncome).order_by(
            RecurringIncome.person, RecurringIncome.source).all()
        if person:
            sources = [s for s in sources if s.person == person]
        retirements = {}
        for source in sources:
            name = MemberIdentityService.label(source.person, source.member_id)
            info = IncomeProjectionService.retirement_for(source.person, source.member_id)
            if info:
                retirements[name] = info
        if until_year is None:
            until_year = IncomeProjectionService.default_until_year(
                [s for s in sources if s.is_active], today,
                [info['date'] for info in retirements.values()])
        try:
            until_year = int(until_year)
        except (TypeError, ValueError):
            raise ValueError('Choose a valid final tax year.')
        until_year = max(first_year, min(until_year, first_year + MAX_PLAN_YEARS))
        window_start = date(first_year, 4, 6)
        window_end = date(until_year + 1, 4, 5)

        settings_cache = {}

        def settings_for(pay_date):
            year = payroll_calculator.tax_year_start(pay_date)
            if year not in settings_cache:
                settings_cache[year] = IncomeService.get_tax_settings_for_date(pay_date)
            return settings_cache[year]

        years = {y: {'start': y, 'label': f'{y}-{(y + 1) % 100:02d}', 'totals': _empty(),
                     'by_person': defaultdict(_empty), 'by_type': defaultdict(_empty), 'projected': False}
                 for y in range(first_year, until_year + 1)}
        source_rows = []
        pensions = {}
        warnings = set()

        changes_by_source = defaultdict(list)
        if sources:
            for change in family_query(IncomeChange).filter(
                IncomeChange.recurring_income_id.in_([s.id for s in sources])
            ).order_by(IncomeChange.effective_date, IncomeChange.id).all():
                changes_by_source[change.recurring_income_id].append(change)

        for source in sources:
            saved = family_query(Income).filter(
                Income.recurring_income_id == source.id,
                Income.pay_date >= window_start, Income.pay_date <= window_end,
            ).order_by(Income.pay_date).all()
            if source.is_active:
                payslips, source_warnings = IncomeProjectionService.payslips(
                    source, window_start, window_end, settings_for, changes_by_source[source.id], saved)
            else:
                # Paused / closed sources only contribute what was actually saved.
                payslips, source_warnings = [(row.pay_date, _from_row(row), True) for row in saved], []
            person_label = MemberIdentityService.label(source.person, source.member_id)
            retirement = retirements.get(person_label)
            if retirement and (source.income_type or 'employment') in WORK_INCOME_TYPES:
                retire_on = retirement['date']
                if any(pay_date > retire_on for pay_date, _, _ in payslips):
                    # Paid / actual payslips are real money; forecasts and projections stop.
                    settled = {row.pay_date for row in saved if row.is_paid or row.is_manual_override}
                    payslips = [p for p in payslips if p[0] <= retire_on or p[0] in settled]
                    if not source.end_date or source.end_date > retire_on:
                        warnings.add(
                            f'{source.source or source.person}: stopped at {source.person}\'s retirement on '
                            f'{retire_on.strftime("%d %b %Y")} in this plan. Set its end date (End income) '
                            'so saved forecasts stop too.')
            if not payslips:
                continue
            warnings.update(f'{source.source or source.person}: {w}' for w in source_warnings)
            per_year = defaultdict(_empty)
            type_key = source.income_type or 'employment'
            for pay_date, values, is_saved in payslips:
                year = payroll_calculator.tax_year_start(pay_date)
                if year not in years:
                    continue
                _add(per_year[year], values)
                _add(years[year]['totals'], values)
                _add(years[year]['by_person'][person_label], values)
                _add(years[year]['by_type'][type_key], values)
                if not is_saved:
                    years[year]['projected'] = True
                if source.pension_id:
                    pot = pensions.setdefault(source.pension_id, {
                        'pension': source.pension, 'years': defaultdict(lambda: ZERO)})
                    pot['years'][year] += values['employee_pension'] + values['employer_pension'] + values['avc']
            source_rows.append({'source': source, 'years': dict(per_year),
                                'fixed': IncomeForecastService.uses_fixed_figures(source)})

        one_offs = family_query(Income).filter(
            Income.recurring_income_id.is_(None),
            Income.pay_date >= window_start, Income.pay_date <= window_end,
        )
        if person:
            one_offs = one_offs.filter(Income.person == person)
        for income in one_offs.all():
            year = payroll_calculator.tax_year_start(income.pay_date)
            values = _from_row(income)
            _add(years[year]['totals'], values)
            _add(years[year]['by_person'][MemberIdentityService.label(income.person, income.member_id)], values)
            _add(years[year]['by_type']['one_off'], values)

        ordered = [years[y] for y in sorted(years)]
        for year in ordered:
            year['by_person'] = dict(year['by_person'])
            year['by_type'] = dict(year['by_type'])
            year['retiring'] = [name for name, info in retirements.items()
                                if payroll_calculator.tax_year_start(info['date']) == year['start']]
        for name, info in retirements.items():
            if info['date'] <= window_end and not any(
                    MemberIdentityService.label(s.person, s.member_id) == name
                    and s.income_type in PENSION_INCOME_TYPES for s in sources):
                warnings.add(f'{name} retires on {info["date"].strftime("%d %b %Y")} but has no pension income source. '
                             'Add one (private or state pension) starting then to see retirement income.')
        return {
            'years': ordered,
            'sources': source_rows,
            'pensions': list(pensions.values()),
            'people': sorted({p for y in ordered for p in y['by_person']}),
            'retirements': retirements,
            'first_year': first_year,
            'until_year': until_year,
            'max_year': first_year + MAX_PLAN_YEARS,
            'warnings': sorted(warnings),
        }
