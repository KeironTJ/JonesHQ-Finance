"""
Payroll Calculator
==================
The single source of truth for UK income estimates: income tax (rUK and Scottish
bands), employee Class 1 NI, self-employed Class 4 NI, workplace pension and
student loan. Pure functions: no database writes, no session use — callers pass in
a tax-settings object (see ``IncomeService.get_tax_settings_for_date``).

Every income flow (forecasts, record edit, live preview) goes through
``calculate_payslip`` (or its monthly wrapper) so figures can never disagree.

Method (documented so nobody mistakes simplifications for bugs)
---------------------------------------------------------------
* Income tax is annualised: period tax = annual tax / periods per year. A bonus is
  taxed at the marginal rate (tax on salary + bonus minus tax on salary), which
  matches the year-end position of cumulative PAYE.
* Employee NI and student loan are calculated per pay period against period
  thresholds (annual / periods), as payroll does.
* 53-week / 27-fortnight years and week-1/month-1 catch-up are not modelled.
* AVCs and "other" deductions are taken from net pay.
* Self-employed tax and Class 4 NI are estimated on annual profit and spread over
  the chosen frequency as a set-aside; they are actually paid via Self Assessment.
* Rental income uses a set-aside percentage because the true tax depends on all of
  that person's other income.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import re

from services.finance import uk_tax_tables


TWO_PLACES = Decimal('0.01')
ZERO = Decimal('0')

PENSION_SCHEMES = ('salary_sacrifice', 'net_pay', 'relief_at_source')
DEFAULT_PENSION_SCHEME = 'salary_sacrifice'
PENSION_SCHEME_LABELS = {
    'salary_sacrifice': 'Salary sacrifice',
    'net_pay': 'Net pay arrangement',
    'relief_at_source': 'Relief at source',
}

PAY_FREQUENCIES = {
    'weekly': 52,
    'fortnightly': 26,
    'four_weekly': 13,
    'monthly': 12,
    'annual': 1,
}
PAY_FREQUENCY_LABELS = {
    'weekly': 'Weekly',
    'fortnightly': 'Fortnightly',
    'four_weekly': 'Every 4 weeks',
    'monthly': 'Monthly',
    'annual': 'Annually / one-off',
}

INCOME_TYPES = (
    'employment', 'private_pension', 'state_pension', 'self_employed',
    'rental', 'benefit', 'other_untaxed',
)
INCOME_TYPE_LABELS = {
    'employment': 'Employment (PAYE)',
    'private_pension': 'Private / workplace pension',
    'state_pension': 'State pension',
    'self_employed': 'Self-employed',
    'rental': 'Rental',
    'benefit': 'Benefits (e.g. child benefit)',
    'other_untaxed': 'Other untaxed',
}
# What each income type is subject to.
PAYE_TYPES = {'employment', 'private_pension'}
CLASS_1_NI_TYPES = {'employment'}
WORKPLACE_PENSION_TYPES = {'employment'}
PAYROLL_STUDENT_LOAN_TYPES = {'employment'}
SET_ASIDE_TYPES = {'rental'}

# Personal allowance is withdrawn by £1 for every £2 of adjusted net income over this.
PA_TAPER_THRESHOLD = Decimal('100000')

_TAX_CODE_RE = re.compile(
    r'^(?P<region>[SC])?'
    r'(?:(?P<special>BR|D0|D1|D2|NT|0T)'
    r'|(?P<k>K)(?P<knum>\d{1,4})'
    r'|(?P<num>\d{1,4})(?P<suffix>[LMNT]))'
    r'(?P<emergency>W1|M1|X)?$'
)


def _d(value):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _q(value):
    return _d(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def tax_year_for(pay_date):
    """UK tax year label for a date: 6 April year N → 5 April year N+1 = 'N-N+1'."""
    start_year = tax_year_start(pay_date)
    return f"{start_year}-{start_year + 1}"


def tax_year_start(pay_date):
    """Calendar year in which the tax year containing *pay_date* starts."""
    return pay_date.year if (pay_date.month, pay_date.day) >= (4, 6) else pay_date.year - 1


@dataclass
class TaxCode:
    raw: str
    region: str = 'rUK'           # 'rUK', 'Scotland' or 'Wales'
    kind: str = 'standard'        # standard | K | BR | D0 | D1 | D2 | NT
    allowance: Decimal = ZERO     # negative for K codes
    suffix: str = ''
    is_emergency: bool = False


def normalise_tax_code(raw):
    return re.sub(r'\s+', '', str(raw or '')).upper()


def parse_tax_code(raw):
    """Parse a UK tax code. Raises ValueError for anything unrecognised."""
    code = normalise_tax_code(raw)
    match = _TAX_CODE_RE.match(code)
    if not match:
        raise ValueError(f"Unrecognised tax code '{raw}'. Examples: 1257L, K475, BR, D0, NT, S1257L.")
    region = {'S': 'Scotland', 'C': 'Wales'}.get(match.group('region'), 'rUK')
    is_emergency = bool(match.group('emergency'))
    special = match.group('special')
    if special == '0T':
        return TaxCode(code, region, 'standard', ZERO, 'T', is_emergency)
    if special:
        return TaxCode(code, region, special, ZERO, '', is_emergency)
    if match.group('k'):
        return TaxCode(code, region, 'K', -Decimal(match.group('knum')) * 10, 'K', is_emergency)
    return TaxCode(
        code, region, 'standard', Decimal(match.group('num')) * 10,
        match.group('suffix'), is_emergency,
    )


def _settings_value(settings, name):
    return _d(getattr(settings, name))


def _bands_for(code, settings, year_start, warnings):
    """Return [(upper limit of taxable income or None, rate), ...]."""
    if code.region == 'Scotland':
        bands, exact = uk_tax_tables.lookup(uk_tax_tables.SCOTTISH_BANDS, year_start)
        if not exact:
            warnings.append(
                f'Scottish bands for {year_start}-{year_start + 1} are not built in; '
                'the latest known bands were used.'
            )
        return bands
    basic_band = _settings_value(settings, 'basic_rate_limit') - _settings_value(settings, 'personal_allowance')
    return [
        (basic_band, _settings_value(settings, 'basic_rate')),
        (_settings_value(settings, 'higher_rate_limit'), _settings_value(settings, 'higher_rate')),
        (None, _settings_value(settings, 'additional_rate')),
    ]


def _flat_rate(code, bands):
    """Rate for BR / D0 / D1 / D2 codes from the band table."""
    rates = [rate for _, rate in bands]
    if code.region == 'Scotland':
        # Scottish: BR = basic (2nd band), D0 higher, D1 advanced, D2 top.
        index = {'BR': 1, 'D0': 3, 'D1': 4, 'D2': 5}[code.kind]
    else:
        index = {'BR': 0, 'D0': 1, 'D1': 2, 'D2': 2}[code.kind]
    return rates[min(index, len(rates) - 1)]


def calculate_annual_income_tax(taxable_pay, tax_code, settings, year_start=None):
    """
    Annual income tax on *taxable_pay* (gross pay after any pre-tax pension).

    Bands are applied to taxable income *after* the allowance, matching HMRC's
    definition. *year_start* (calendar year the tax year starts) selects the
    Scottish band table; it defaults to the current tax year.

    Returns (tax, warnings).
    """
    taxable_pay = max(ZERO, _d(taxable_pay))
    code = tax_code if isinstance(tax_code, TaxCode) else parse_tax_code(tax_code)
    warnings = []
    year_start = year_start if year_start is not None else tax_year_start(date.today())
    bands = _bands_for(code, settings, year_start, warnings)

    if code.kind == 'NT':
        return ZERO, warnings
    if code.kind in ('BR', 'D0', 'D1', 'D2'):
        return taxable_pay * _flat_rate(code, bands), warnings

    standard_pa = _settings_value(settings, 'personal_allowance')
    allowance = code.allowance
    # Only taper a code that still carries the full standard allowance; a reduced
    # code (e.g. 0T or 500L) means HMRC has already applied the taper.
    if code.kind == 'standard' and allowance == standard_pa and taxable_pay > PA_TAPER_THRESHOLD:
        allowance = max(ZERO, allowance - (taxable_pay - PA_TAPER_THRESHOLD) / 2)

    taxable_income = max(ZERO, taxable_pay - allowance)
    tax = ZERO
    lower = ZERO
    for upper, rate in bands:
        if upper is None or taxable_income <= upper:
            tax += (taxable_income - lower) * rate
            break
        tax += (upper - lower) * rate
        lower = upper

    if code.kind == 'K':
        # Overriding limit: K-code tax can't exceed 50% of pay.
        tax = min(tax, taxable_pay / 2)
    return tax, warnings


def _class_1_ni(pay, threshold, upper, main_rate, upper_rate):
    pay = max(ZERO, _d(pay))
    main = max(ZERO, min(pay, upper) - threshold)
    above = max(ZERO, pay - max(upper, threshold))
    return main * main_rate + above * upper_rate


def calculate_annual_ni(ni_pay, settings):
    """Annual employee Class 1 NI on *ni_pay*."""
    return _class_1_ni(
        ni_pay,
        _settings_value(settings, 'ni_threshold'),
        _settings_value(settings, 'ni_upper_earnings'),
        _settings_value(settings, 'ni_basic_rate'),
        _settings_value(settings, 'ni_additional_rate'),
    )


def calculate_period_ni(ni_pay, settings, periods):
    """Employee Class 1 NI for one pay period, using period thresholds."""
    return _class_1_ni(
        ni_pay,
        _settings_value(settings, 'ni_threshold') / periods,
        _settings_value(settings, 'ni_upper_earnings') / periods,
        _settings_value(settings, 'ni_basic_rate'),
        _settings_value(settings, 'ni_additional_rate'),
    )


def calculate_class_4_ni(profit, year_start):
    """Annual self-employed Class 4 NI. Returns (ni, warnings)."""
    (lower, upper, main_rate, upper_rate), exact = uk_tax_tables.lookup(uk_tax_tables.CLASS_4_NI, year_start)
    warnings = [] if exact else [f'Class 4 NI rates for {year_start}-{year_start + 1} assumed unchanged.']
    return _class_1_ni(profit, lower, upper, main_rate, upper_rate), warnings


def normalise_student_loan_plans(plans):
    """Validate a list/CSV of plan keys; returns a sorted tuple."""
    if isinstance(plans, str):
        plans = [p for p in plans.split(',') if p.strip()]
    cleaned = tuple(sorted({str(p).strip() for p in (plans or ())}))
    for plan in cleaned:
        if plan not in uk_tax_tables.STUDENT_LOAN_PLANS:
            raise ValueError(f"Unknown student loan plan '{plan}'.")
    return cleaned


def calculate_student_loan(pay, plans, year_start, periods):
    """
    Student loan deduction for one period (payroll method). With more than one
    undergraduate plan, payroll uses the lowest threshold; a postgraduate loan is
    deducted on top. Deductions are rounded down to whole pounds.

    Returns (amount, warnings).
    """
    plans = normalise_student_loan_plans(plans)
    if not plans:
        return ZERO, []
    table, exact = uk_tax_tables.lookup(uk_tax_tables.STUDENT_LOAN, year_start)
    warnings = [] if exact else [f'Student loan thresholds for {year_start}-{year_start + 1} assumed unchanged.']
    pay = max(ZERO, _d(pay))
    total = ZERO
    undergrad = [table[p] for p in plans if p != 'postgrad']
    if undergrad:
        threshold, rate = min(undergrad, key=lambda item: item[0])
        total += (max(ZERO, pay - threshold / periods) * rate).quantize(Decimal('1'), rounding=ROUND_DOWN)
    if 'postgrad' in plans:
        threshold, rate = table['postgrad']
        total += (max(ZERO, pay - threshold / periods) * rate).quantize(Decimal('1'), rounding=ROUND_DOWN)
    return total, warnings


@dataclass
class PayslipEstimate:
    tax_year: str
    gross_annual: Decimal
    gross_period: Decimal          # base pay + bonus for this pay date
    employee_pension: Decimal
    employer_pension: Decimal
    total_pension: Decimal
    adjusted_period: Decimal       # gross_period - employee pension
    adjusted_annual: Decimal
    income_tax: Decimal
    national_insurance: Decimal
    avc: Decimal
    other_deductions: Decimal
    take_home: Decimal
    annual_tax: Decimal            # on base pay, excluding any bonus
    annual_ni: Decimal
    pension_scheme: str
    student_loan: Decimal = ZERO
    bonus: Decimal = ZERO
    frequency: str = 'monthly'
    periods_per_year: int = 12
    income_type: str = 'employment'
    warnings: list = field(default_factory=list)

    # Back-compat names used by monthly callers and older templates.
    @property
    def gross_monthly(self):
        return self.gross_period

    @property
    def adjusted_monthly(self):
        return self.adjusted_period

    def as_dict(self):
        data = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}
        data['gross_monthly'] = data['gross_period']
        data['adjusted_monthly'] = data['adjusted_period']
        return data


def _choice(value, options, label):
    if value not in options:
        raise ValueError(f"Unknown {label} '{value}'.")
    return value


def calculate_payslip(
    gross_annual, tax_code, settings, pay_date=None, *,
    frequency='monthly', income_type='employment',
    employee_pension_pct=0, employer_pension_pct=0, pension_scheme=DEFAULT_PENSION_SCHEME,
    avc=0, other=0, student_loan_plans=(), bonus=0, bonus_pensionable=False,
    set_aside_pct=0,
):
    """
    Estimate the payment for one pay date.

    gross_annual   — annual salary / pension / profit / rent before deductions.
    bonus          — one-off amount paid on this date on top of normal pay.
    avc, other     — per-period deductions from net pay.
    set_aside_pct  — rental: % of gross put aside for tax (shown as income tax).

    pension_scheme:
      salary_sacrifice — employee pension reduces both taxable and NI-able pay.
      net_pay          — reduces taxable pay only; NI is on full gross.
      relief_at_source — taken from net pay at 80% (basic-rate relief is added
                         by the provider); tax and NI are on full gross.
    """
    _choice(pension_scheme, PENSION_SCHEMES, 'pension scheme')
    _choice(frequency, PAY_FREQUENCIES, 'pay frequency')
    _choice(income_type, INCOME_TYPES, 'income type')
    periods = PAY_FREQUENCIES[frequency]
    pay_date = pay_date or date.today()
    year_start = tax_year_start(pay_date)
    warnings = []

    gross_annual = _d(gross_annual)
    bonus = _d(bonus)
    avc = _d(avc)
    other = _d(other)
    if gross_annual < 0 or bonus < 0:
        raise ValueError('Pay and bonus cannot be negative.')

    base_period = gross_annual / periods
    gross_period = _q(base_period + bonus)

    # Workplace pension (employment only).
    employee_pct = _d(employee_pension_pct) if income_type in WORKPLACE_PENSION_TYPES else ZERO
    employer_pct = _d(employer_pension_pct) if income_type in WORKPLACE_PENSION_TYPES else ZERO
    pensionable_bonus = bonus if bonus_pensionable else ZERO
    employee_pension = _q((base_period + pensionable_bonus) * employee_pct / 100)
    employer_pension = _q((base_period + pensionable_bonus) * employer_pct / 100)
    base_employee_pension = _q(base_period * employee_pct / 100)
    bonus_employee_pension = employee_pension - base_employee_pension

    pre_tax = pension_scheme in ('salary_sacrifice', 'net_pay')
    pre_ni = pension_scheme == 'salary_sacrifice'
    if pension_scheme == 'relief_at_source':
        pension_from_net = _q(employee_pension * Decimal('0.8'))
    else:
        pension_from_net = employee_pension

    taxable_annual = gross_annual - (base_employee_pension * periods if pre_tax else ZERO)
    taxable_bonus = bonus - (bonus_employee_pension if pre_tax else ZERO)

    annual_tax = annual_ni = ZERO
    period_tax = period_ni = student_loan = ZERO

    if income_type in PAYE_TYPES:
        annual_tax, tax_warnings = calculate_annual_income_tax(taxable_annual, tax_code, settings, year_start)
        warnings += tax_warnings
        period_tax = annual_tax / periods
        if taxable_bonus:
            with_bonus, _ = calculate_annual_income_tax(
                taxable_annual + taxable_bonus, tax_code, settings, year_start,
            )
            period_tax += with_bonus - annual_tax

    if income_type in CLASS_1_NI_TYPES:
        ni_period_pay = base_period + bonus - (
            (base_employee_pension + bonus_employee_pension) if pre_ni else ZERO
        )
        annual_ni = calculate_annual_ni(gross_annual - (base_employee_pension * periods if pre_ni else ZERO), settings)
        period_ni = calculate_period_ni(ni_period_pay, settings, periods)
        if income_type in PAYROLL_STUDENT_LOAN_TYPES:
            student_loan, sl_warnings = calculate_student_loan(ni_period_pay, student_loan_plans, year_start, periods)
            warnings += sl_warnings

    if income_type == 'self_employed':
        if _d(set_aside_pct) > 0:
            annual_tax = gross_annual * _d(set_aside_pct) / 100
            period_tax = annual_tax / periods + bonus * _d(set_aside_pct) / 100
        else:
            annual_tax, tax_warnings = calculate_annual_income_tax(gross_annual, tax_code, settings, year_start)
            warnings += tax_warnings
            annual_ni, ni_warnings = calculate_class_4_ni(gross_annual, year_start)
            warnings += ni_warnings
            period_tax = annual_tax / periods
            period_ni = annual_ni / periods
            if bonus:
                tax_with, _ = calculate_annual_income_tax(gross_annual + bonus, tax_code, settings, year_start)
                ni_with, _ = calculate_class_4_ni(gross_annual + bonus, year_start)
                period_tax += tax_with - annual_tax
                period_ni += ni_with - annual_ni
            sl_annual, sl_warnings = calculate_student_loan(gross_annual + bonus, student_loan_plans, year_start, 1)
            warnings += sl_warnings
            student_loan = _q(sl_annual / periods)
        warnings.append('Self-employed tax is a set-aside estimate; it is paid through Self Assessment.')

    if income_type in SET_ASIDE_TYPES:
        rate = _d(set_aside_pct)
        annual_tax = gross_annual * rate / 100
        period_tax = (base_period + bonus) * rate / 100
        if rate == 0:
            warnings.append('No tax is being set aside for this rental income.')

    if income_type == 'state_pension':
        warnings.append('State pension is paid gross; its tax is usually collected through the tax code on other income.')

    period_tax = _q(period_tax)
    period_ni = _q(period_ni)
    take_home = _q(gross_period - pension_from_net - period_tax - period_ni - student_loan - avc - other)
    if take_home < 0:
        warnings.append('Deductions exceed gross pay; take home is negative.')

    return PayslipEstimate(
        tax_year=tax_year_for(pay_date),
        gross_annual=_q(gross_annual),
        gross_period=gross_period,
        employee_pension=employee_pension,
        employer_pension=employer_pension,
        total_pension=_q(employee_pension + employer_pension),
        adjusted_period=_q(gross_period - employee_pension),
        adjusted_annual=_q(gross_annual - base_employee_pension * periods),
        income_tax=period_tax,
        national_insurance=period_ni,
        avc=_q(avc),
        other_deductions=_q(other),
        take_home=take_home,
        annual_tax=_q(annual_tax),
        annual_ni=_q(annual_ni),
        pension_scheme=pension_scheme,
        student_loan=_q(student_loan),
        bonus=_q(bonus),
        frequency=frequency,
        periods_per_year=periods,
        income_type=income_type,
        warnings=warnings,
    )


def calculate_monthly_payslip(
    gross_annual, tax_code, settings, pay_date=None, employee_pension_pct=0,
    employer_pension_pct=0, avc=0, other=0, pension_scheme=DEFAULT_PENSION_SCHEME,
):
    """Monthly employment payslip — kept for existing callers."""
    return calculate_payslip(
        gross_annual, tax_code, settings, pay_date,
        employee_pension_pct=employee_pension_pct, employer_pension_pct=employer_pension_pct,
        avc=avc, other=other, pension_scheme=pension_scheme,
    )
