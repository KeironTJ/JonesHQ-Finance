"""
Built-in UK statutory tables that household tax settings don't store.

rUK income-tax bands and Class 1 NI come from ``TaxSettings`` (editable per tax
year). The tables here cover Scottish bands, student-loan thresholds and
self-employed Class 4 NI. They are keyed by the tax year's starting calendar
year; a year that isn't listed uses the latest earlier one and the calculator
returns a warning so stale figures are visible. Update these each April.
"""
from decimal import Decimal as D


# Scottish bands as (upper limit of *taxable* income after allowance, rate).
# The final band has no upper limit (None). Above the personal-allowance
# taper the higher bands mirror rUK, so only the band table differs.
SCOTTISH_BANDS = {
    2024: [
        (D('2306'), D('0.19')),
        (D('13991'), D('0.20')),
        (D('31092'), D('0.21')),
        (D('62430'), D('0.42')),
        (D('125140'), D('0.45')),
        (None, D('0.48')),
    ],
    2025: [
        (D('2827'), D('0.19')),
        (D('14921'), D('0.20')),
        (D('31092'), D('0.21')),
        (D('62430'), D('0.42')),
        (D('125140'), D('0.45')),
        (None, D('0.48')),
    ],
    2026: [
        (D('3967'), D('0.19')),
        (D('16956'), D('0.20')),
        (D('31092'), D('0.21')),
        (D('62430'), D('0.42')),
        (D('125140'), D('0.45')),
        (None, D('0.48')),
    ],
}

# Student loan: annual threshold and rate per plan.
STUDENT_LOAN_PLANS = ('plan_1', 'plan_2', 'plan_4', 'plan_5', 'postgrad')
STUDENT_LOAN_LABELS = {
    'plan_1': 'Plan 1', 'plan_2': 'Plan 2', 'plan_4': 'Plan 4 (Scotland)',
    'plan_5': 'Plan 5', 'postgrad': 'Postgraduate',
}
STUDENT_LOAN = {
    2024: {
        'plan_1': (D('24990'), D('0.09')),
        'plan_2': (D('27295'), D('0.09')),
        'plan_4': (D('31395'), D('0.09')),
        'plan_5': (D('25000'), D('0.09')),
        'postgrad': (D('21000'), D('0.06')),
    },
    2025: {
        'plan_1': (D('26065'), D('0.09')),
        'plan_2': (D('28470'), D('0.09')),
        'plan_4': (D('32745'), D('0.09')),
        'plan_5': (D('25000'), D('0.09')),
        'postgrad': (D('21000'), D('0.06')),
    },
    2026: {
        'plan_1': (D('26900'), D('0.09')),
        'plan_2': (D('29385'), D('0.09')),
        'plan_4': (D('33795'), D('0.09')),
        'plan_5': (D('25000'), D('0.09')),
        'postgrad': (D('21000'), D('0.06')),
    },
}

# Self-employed Class 4 NI: lower profits limit, upper profits limit, main rate, upper rate.
CLASS_4_NI = {
    2024: (D('12570'), D('50270'), D('0.06'), D('0.02')),
    2025: (D('12570'), D('50270'), D('0.06'), D('0.02')),
    2026: (D('12570'), D('50270'), D('0.06'), D('0.02')),
}


def lookup(table, tax_year_start):
    """Return (value, exact) — the entry for the year, or the latest earlier one."""
    if tax_year_start in table:
        return table[tax_year_start], True
    earlier = [year for year in table if year <= tax_year_start]
    year = max(earlier) if earlier else min(table)
    return table[year], False
