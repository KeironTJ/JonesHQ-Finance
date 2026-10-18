from datetime import date
from decimal import Decimal

import pytest

from services.finance import payroll_calculator as pc


class Settings2025:
    personal_allowance = Decimal('12570')
    basic_rate_limit = Decimal('50270')
    higher_rate_limit = Decimal('125140')
    basic_rate = Decimal('0.20')
    higher_rate = Decimal('0.40')
    additional_rate = Decimal('0.45')
    ni_threshold = Decimal('12570')
    ni_upper_earnings = Decimal('50270')
    ni_basic_rate = Decimal('0.08')
    ni_additional_rate = Decimal('0.02')


S = Settings2025()


def annual_tax(pay, code='1257L'):
    tax, _ = pc.calculate_annual_income_tax(Decimal(pay), code, S)
    return tax.quantize(Decimal('0.01'))


@pytest.mark.parametrize('pay,expected', [
    ('12570', '0.00'),
    ('30000', '3486.00'),
    ('50270', '7540.00'),
    ('60000', '11432.00'),
    ('110000', '33432.00'),   # personal allowance tapered to £7,570
    ('125140', '42516.00'),   # allowance fully withdrawn
    ('150000', '53703.00'),
])
def test_standard_code_bands_and_taper(pay, expected):
    assert annual_tax(pay) == Decimal(expected)


@pytest.mark.parametrize('code,pay,expected', [
    ('BR', '20000', '4000.00'),
    ('D0', '20000', '8000.00'),
    ('D1', '20000', '9000.00'),
    ('NT', '80000', '0.00'),
    ('0T', '30000', '6000.00'),
    ('K475', '30000', '6950.00'),
    ('1257LW1', '30000', '3486.00'),
    ('C1257L', '30000', '3486.00'),
    (' 1257l ', '30000', '3486.00'),
])
def test_special_tax_codes(code, pay, expected):
    assert annual_tax(pay, code) == Decimal(expected)


def test_k_code_tax_is_capped_at_half_of_pay():
    assert annual_tax('10000', 'K9999') == Decimal('5000.00')


def test_reduced_code_is_not_tapered_twice():
    # 500L already reflects HMRC's reduced allowance.
    assert annual_tax('110000', '500L') == Decimal('34460.00')


def test_scottish_code_warns():
    _, warnings = pc.calculate_annual_income_tax(Decimal('30000'), 'S1257L', S)
    assert warnings and 'Scottish' in warnings[0]


@pytest.mark.parametrize('code', ['', 'ABC', '1257', '1257X', 'K', '12345678L'])
def test_invalid_tax_codes_raise(code):
    with pytest.raises(ValueError):
        pc.parse_tax_code(code)


@pytest.mark.parametrize('pay,expected', [
    ('12570', '0.00'),
    ('30000', '1394.40'),
    ('60000', '3210.60'),
])
def test_national_insurance(pay, expected):
    assert pc.calculate_annual_ni(Decimal(pay), S).quantize(Decimal('0.01')) == Decimal(expected)


@pytest.mark.parametrize('day,expected', [
    (date(2026, 4, 5), '2025-2026'),
    (date(2026, 4, 6), '2026-2027'),
    (date(2026, 1, 31), '2025-2026'),
    (date(2026, 12, 25), '2026-2027'),
])
def test_tax_year_starts_on_6_april(day, expected):
    assert pc.tax_year_for(day) == expected


def test_monthly_payslip_without_pension():
    est = pc.calculate_monthly_payslip('30000', '1257L', S, date(2026, 5, 28))
    assert est.gross_monthly == Decimal('2500.00')
    assert est.income_tax == Decimal('290.50')
    assert est.national_insurance == Decimal('116.20')
    assert est.take_home == Decimal('2093.30')
    assert est.tax_year == '2026-2027'


def test_salary_sacrifice_pension_is_deducted_from_taxable_pay_only_once():
    est = pc.calculate_monthly_payslip(
        '50000', '1257L', S, date(2026, 5, 28), employee_pension_pct=5, employer_pension_pct=3,
    )
    assert est.employee_pension == Decimal('208.33')
    assert est.employer_pension == Decimal('125.00')
    taxable = Decimal('50000') - Decimal('208.33') * 12
    assert est.annual_tax == ((taxable - 12570) * Decimal('0.20')).quantize(Decimal('0.01'))
    assert est.annual_ni == ((taxable - 12570) * Decimal('0.08')).quantize(Decimal('0.01'))
    assert est.take_home == (
        est.gross_monthly - est.employee_pension - est.income_tax - est.national_insurance
    )


def test_net_pay_scheme_charges_ni_on_full_gross():
    est = pc.calculate_monthly_payslip(
        '50000', '1257L', S, employee_pension_pct=5, pension_scheme='net_pay',
    )
    assert est.annual_ni == ((Decimal('50000') - 12570) * Decimal('0.08')).quantize(Decimal('0.01'))


def test_relief_at_source_takes_80_percent_from_net_pay():
    est = pc.calculate_monthly_payslip(
        '30000', '1257L', S, employee_pension_pct=5, pension_scheme='relief_at_source',
    )
    assert est.annual_tax == Decimal('3486.00')
    assert est.take_home == Decimal('2093.30') - Decimal('100.00')


def test_post_tax_deductions_reduce_take_home():
    est = pc.calculate_monthly_payslip('30000', '1257L', S, avc=50, other=10)
    assert est.take_home == Decimal('2033.30')


def test_unknown_pension_scheme_rejected():
    with pytest.raises(ValueError):
        pc.calculate_monthly_payslip('30000', '1257L', S, pension_scheme='magic')
