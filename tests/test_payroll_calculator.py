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


def test_scottish_bands_2025():
    # Taxable 17,430: 2,827 @19% + 12,094 @20% + 2,509 @21%
    tax, warnings = pc.calculate_annual_income_tax(Decimal('30000'), 'S1257L', S, year_start=2025)
    assert tax.quantize(Decimal('0.01')) == Decimal('3482.82')
    assert warnings == []
    tax, _ = pc.calculate_annual_income_tax(Decimal('60000'), 'S1257L', S, year_start=2025)
    assert tax.quantize(Decimal('0.01')) == Decimal('13213.80')


def test_scottish_flat_codes_use_scottish_rates():
    tax, _ = pc.calculate_annual_income_tax(Decimal('10000'), 'SD0', S, year_start=2025)
    assert tax == Decimal('4200.00')


def test_scottish_unknown_year_warns_and_uses_latest_bands():
    tax, warnings = pc.calculate_annual_income_tax(Decimal('30000'), 'S1257L', S, year_start=2030)
    # Latest built-in bands (2026-27): 3,967 @19% + 12,989 @20% + 474 @21%
    assert tax.quantize(Decimal('0.01')) == Decimal('3451.07')
    assert warnings and 'Scottish' in warnings[0]


def test_welsh_code_uses_ruk_bands():
    assert annual_tax('30000', 'C1257L') == Decimal('3486.00')


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


# --- Frequencies, bonuses, student loans and income types -----------------------

MAY_2025 = date(2025, 5, 28)


def payslip(gross='30000', **kwargs):
    kwargs.setdefault('pay_date', MAY_2025)
    pay_date = kwargs.pop('pay_date')
    code = kwargs.pop('tax_code', '1257L')
    return pc.calculate_payslip(gross, code, S, pay_date, **kwargs)


def test_weekly_pay_uses_period_ni_thresholds():
    est = payslip(frequency='weekly')
    assert est.periods_per_year == 52
    assert est.gross_period == Decimal('576.92')
    assert est.income_tax == Decimal('67.04')
    assert est.national_insurance == Decimal('26.82')
    assert est.take_home == Decimal('483.06')


@pytest.mark.parametrize('frequency,periods', [
    ('fortnightly', 26), ('four_weekly', 13), ('monthly', 12), ('annual', 1),
])
def test_constant_pay_frequencies_sum_to_annual_figures(frequency, periods):
    est = payslip(frequency=frequency)
    assert abs(est.income_tax * periods - Decimal('3486')) < periods * Decimal('0.01')
    assert abs(est.national_insurance * periods - Decimal('1394.40')) < periods * Decimal('0.01')


def test_bonus_taxed_at_marginal_rate_and_ni_per_period():
    est = payslip(bonus='5000')
    assert est.gross_period == Decimal('7500.00')
    assert est.income_tax == Decimal('1290.50')
    assert est.national_insurance == Decimal('317.55')
    assert est.take_home == Decimal('5891.95')
    assert est.annual_tax == Decimal('3486.00')


def test_pensionable_bonus_attracts_pension():
    est = payslip(bonus='1000', employee_pension_pct=5, bonus_pensionable=True)
    assert est.employee_pension == Decimal('175.00')
    assert payslip(bonus='1000', employee_pension_pct=5).employee_pension == Decimal('125.00')


def test_student_loan_plan_2_and_postgrad_round_down_separately():
    est = payslip('40000', student_loan_plans=['plan_2', 'postgrad'])
    # plan 2: (3333.33 - 2372.50) x 9% = 86.47 -> 86; PG: (3333.33 - 1750) x 6% = 94.99 -> 94
    assert est.student_loan == Decimal('180.00')
    assert est.take_home == (
        est.gross_period - est.income_tax - est.national_insurance - est.student_loan
    )


def test_multiple_undergraduate_plans_use_lowest_threshold():
    est = payslip('40000', student_loan_plans='plan_1,plan_4')
    # plan 1 threshold 26,065 / 12 = 2172.08
    assert est.student_loan == Decimal('104.00')


def test_student_loan_below_threshold_is_zero_and_unknown_plan_rejected():
    assert payslip('20000', student_loan_plans=['plan_2']).student_loan == 0
    with pytest.raises(ValueError):
        payslip(student_loan_plans=['plan_9'])


def test_private_pension_has_tax_but_no_ni_or_contributions():
    est = payslip('20000', income_type='private_pension', employee_pension_pct=5)
    assert est.income_tax == Decimal('123.83')
    assert est.national_insurance == 0
    assert est.employee_pension == 0


def test_state_pension_is_paid_gross():
    est = payslip('11973', income_type='state_pension')
    assert est.take_home == Decimal('997.75')
    assert est.income_tax == 0 and est.national_insurance == 0
    assert any('State pension' in w for w in est.warnings)


def test_self_employed_estimates_tax_and_class_4():
    est = payslip('40000', income_type='self_employed')
    assert est.income_tax == Decimal('457.17')
    assert est.national_insurance == Decimal('137.15')
    assert any('Self Assessment' in w for w in est.warnings)


def test_self_employed_set_aside_overrides_estimate():
    est = payslip('40000', income_type='self_employed', set_aside_pct=25)
    assert est.income_tax == Decimal('833.33')
    assert est.national_insurance == 0


def test_rental_uses_set_aside_and_benefits_are_untaxed():
    assert payslip('12000', income_type='rental', set_aside_pct=20).income_tax == Decimal('200.00')
    assert any('rental' in w for w in payslip('12000', income_type='rental').warnings)
    benefit = payslip('1354.60', income_type='benefit', frequency='four_weekly')
    assert benefit.take_home == Decimal('104.20') and benefit.income_tax == 0


@pytest.mark.parametrize('kwargs', [
    {'frequency': 'daily'}, {'income_type': 'lottery'}, {'bonus': '-1'},
])
def test_invalid_payslip_inputs_rejected(kwargs):
    with pytest.raises(ValueError):
        payslip(**kwargs)


def test_as_dict_keeps_monthly_aliases():
    data = payslip().as_dict()
    assert data['gross_monthly'] == data['gross_period'] == 2500.0
