"""
Payroll Calculator
==================
The single source of truth for UK PAYE estimates (income tax, employee Class 1
NI and workplace pension). Pure functions: no database writes, no session use —
callers pass in a tax-settings object (see ``IncomeService.get_tax_settings_for_date``).

Every income flow (template generation, record edit, AJAX preview) must go through
``calculate_monthly_payslip`` so the figures can never disagree with each other.

Simplifications (documented so nobody mistakes them for bugs)
-------------------------------------------------------------
* Annualised calculation: the monthly figure is annual / 12, i.e. it assumes the
  same pay every period (no cumulative PAYE catch-up, no week-1/month-1 effects).
* Scottish (``S``) codes are recognised but taxed with rUK bands because tax
  settings do not yet store Scottish bands — a warning is returned.
* AVCs and "other" deductions are post-tax deductions from net pay.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re


TWO_PLACES = Decimal('0.01')
ZERO = Decimal('0')

PENSION_SCHEMES = ('salary_sacrifice', 'net_pay', 'relief_at_source')
DEFAULT_PENSION_SCHEME = 'salary_sacrifice'

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
    start_year = pay_date.year if (pay_date.month, pay_date.day) >= (4, 6) else pay_date.year - 1
    return f"{start_year}-{start_year + 1}"


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


def calculate_annual_income_tax(taxable_pay, tax_code, settings):
    """
    Annual income tax on *taxable_pay* (gross pay after any pre-tax pension).

    Bands are applied to taxable income *after* the allowance: the basic band is a
    fixed width (basic_rate_limit - standard personal allowance) and the additional
    rate starts at higher_rate_limit of taxable income, matching HMRC's definition.
    """
    taxable_pay = max(ZERO, _d(taxable_pay))
    code = tax_code if isinstance(tax_code, TaxCode) else parse_tax_code(tax_code)
    warnings = []

    basic_rate = _settings_value(settings, 'basic_rate')
    higher_rate = _settings_value(settings, 'higher_rate')
    additional_rate = _settings_value(settings, 'additional_rate')
    standard_pa = _settings_value(settings, 'personal_allowance')
    basic_band = _settings_value(settings, 'basic_rate_limit') - standard_pa
    additional_threshold = _settings_value(settings, 'higher_rate_limit')

    if code.region == 'Scotland':
        warnings.append('Scottish tax bands are not configured; rUK bands were used.')

    if code.kind == 'NT':
        return ZERO, warnings
    if code.kind == 'BR':
        return taxable_pay * basic_rate, warnings
    if code.kind == 'D0':
        return taxable_pay * higher_rate, warnings
    if code.kind in ('D1', 'D2'):
        return taxable_pay * additional_rate, warnings

    allowance = code.allowance
    # Only taper a code that still carries the full standard allowance; a reduced
    # code (e.g. 0T or 500L) means HMRC has already applied the taper.
    if code.kind == 'standard' and allowance == standard_pa and taxable_pay > PA_TAPER_THRESHOLD:
        allowance = max(ZERO, allowance - (taxable_pay - PA_TAPER_THRESHOLD) / 2)

    taxable_income = max(ZERO, taxable_pay - allowance)
    basic_part = min(taxable_income, basic_band)
    higher_part = min(max(ZERO, taxable_income - basic_band), additional_threshold - basic_band)
    additional_part = max(ZERO, taxable_income - additional_threshold)
    tax = basic_part * basic_rate + higher_part * higher_rate + additional_part * additional_rate

    if code.kind == 'K':
        # Overriding limit: K-code tax can't exceed 50% of pay.
        tax = min(tax, taxable_pay / 2)
    return tax, warnings


def calculate_annual_ni(ni_pay, settings):
    """Annual employee Class 1 NI on *ni_pay*."""
    ni_pay = max(ZERO, _d(ni_pay))
    threshold = _settings_value(settings, 'ni_threshold')
    upper = _settings_value(settings, 'ni_upper_earnings')
    main = max(ZERO, min(ni_pay, upper) - threshold)
    above = max(ZERO, ni_pay - max(upper, threshold))
    return main * _settings_value(settings, 'ni_basic_rate') + above * _settings_value(settings, 'ni_additional_rate')


@dataclass
class PayslipEstimate:
    tax_year: str
    gross_annual: Decimal
    gross_monthly: Decimal
    employee_pension: Decimal
    employer_pension: Decimal
    total_pension: Decimal
    adjusted_monthly: Decimal
    adjusted_annual: Decimal
    income_tax: Decimal
    national_insurance: Decimal
    avc: Decimal
    other_deductions: Decimal
    take_home: Decimal
    annual_tax: Decimal
    annual_ni: Decimal
    pension_scheme: str
    warnings: list = field(default_factory=list)

    def as_dict(self):
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


def calculate_monthly_payslip(
    gross_annual, tax_code, settings, pay_date=None, employee_pension_pct=0,
    employer_pension_pct=0, avc=0, other=0, pension_scheme=DEFAULT_PENSION_SCHEME,
):
    """
    Estimate one month's payslip.

    pension_scheme:
      salary_sacrifice — employee pension reduces both taxable and NI-able pay.
      net_pay          — reduces taxable pay only; NI is on full gross.
      relief_at_source — taken from net pay at 80% (basic-rate relief is added
                         by the provider); tax and NI are on full gross.
    """
    if pension_scheme not in PENSION_SCHEMES:
        raise ValueError(f"Unknown pension scheme '{pension_scheme}'.")
    gross_annual = _d(gross_annual)
    employee_pension_pct = _d(employee_pension_pct)
    employer_pension_pct = _d(employer_pension_pct)
    avc = _d(avc)
    other = _d(other)
    pay_date = pay_date or date.today()

    gross_monthly = _q(gross_annual / 12)
    employee_pension = _q(gross_monthly * employee_pension_pct / 100)
    employer_pension = _q(gross_monthly * employer_pension_pct / 100)
    employee_pension_annual = employee_pension * 12

    if pension_scheme == 'salary_sacrifice':
        taxable_annual = gross_annual - employee_pension_annual
        ni_annual_pay = gross_annual - employee_pension_annual
        pension_from_net = employee_pension
    elif pension_scheme == 'net_pay':
        taxable_annual = gross_annual - employee_pension_annual
        ni_annual_pay = gross_annual
        pension_from_net = employee_pension
    else:
        taxable_annual = gross_annual
        ni_annual_pay = gross_annual
        pension_from_net = _q(employee_pension * Decimal('0.8'))

    annual_tax, warnings = calculate_annual_income_tax(taxable_annual, tax_code, settings)
    annual_ni = calculate_annual_ni(ni_annual_pay, settings)
    monthly_tax = _q(annual_tax / 12)
    monthly_ni = _q(annual_ni / 12)

    take_home = _q(gross_monthly - pension_from_net - monthly_tax - monthly_ni - avc - other)
    if take_home < 0:
        warnings.append('Deductions exceed gross pay; take home is negative.')

    return PayslipEstimate(
        tax_year=tax_year_for(pay_date),
        gross_annual=_q(gross_annual),
        gross_monthly=gross_monthly,
        employee_pension=employee_pension,
        employer_pension=employer_pension,
        total_pension=_q(employee_pension + employer_pension),
        adjusted_monthly=_q(gross_monthly - employee_pension),
        adjusted_annual=_q(gross_annual - employee_pension_annual),
        income_tax=monthly_tax,
        national_insurance=monthly_ni,
        avc=_q(avc),
        other_deductions=_q(other),
        take_home=take_home,
        annual_tax=_q(annual_tax),
        annual_ni=_q(annual_ni),
        pension_scheme=pension_scheme,
        warnings=warnings,
    )
