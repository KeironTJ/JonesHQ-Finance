from datetime import date
from decimal import Decimal

from extensions import db
from models.expenses import Expense
from services.work_expense_mileage_service import WorkExpenseMileageService


def _add_expense(family_id, d, desc, miles, rate, days=1, vehicle='AB12 CDE', submitted=False, reimbursed=False):
    total = (Decimal(str(miles)) * Decimal(str(rate)) * Decimal(str(days))).quantize(Decimal('0.01'))
    exp = Expense(
        family_id=family_id,
        date=d,
        month=d.strftime('%Y-%m'),
        week=f"{d.isocalendar()[1]:02d}-{d.year}",
        day_name=d.strftime('%A'),
        finance_year='2025-2026',
        description=desc,
        expense_type='Fuel',
        covered_miles=miles,
        rate_per_mile=Decimal(str(rate)),
        days=days,
        cost=total,
        total_cost=total,
        vehicle_registration=vehicle,
        submitted=submitted,
        reimbursed=reimbursed,
    )
    db.session.add(exp)
    db.session.commit()
    return exp


def test_current_finance_year_boundaries():
    assert WorkExpenseMileageService.current_finance_year(date(2026, 4, 1)) == '2026-2027'
    assert WorkExpenseMileageService.current_finance_year(date(2026, 3, 31)) == '2025-2026'


def test_parse_finance_year():
    start, end = WorkExpenseMileageService.parse_finance_year('2025-2026')
    assert start == date(2025, 4, 1)
    assert end == date(2026, 3, 31)


def test_parse_finance_year_invalid():
    try:
        WorkExpenseMileageService.parse_finance_year('2025/2026')
        assert False, 'Expected ValueError for invalid format'
    except ValueError:
        assert True


def test_build_report_and_csv(app, family):
    _add_expense(family.id, date(2025, 4, 15), 'Trip A', miles=10, rate='0.45', days=2, vehicle='AAA 111')
    _add_expense(family.id, date(2025, 5, 10), 'Trip B', miles=20, rate='0.50', days=1, vehicle='BBB 222', submitted=True)
    _add_expense(family.id, date(2025, 5, 18), 'Trip C', miles=5, rate='0.50', days=1, vehicle='AAA 111', reimbursed=True)

    expenses = WorkExpenseMileageService.mileage_expenses('2025-2026')
    report = WorkExpenseMileageService.build_report(expenses, '2025-2026')

    assert report['summary']['entries'] == 3
    assert report['summary']['miles'] == 45
    assert report['summary']['amount'] == 21.5

    monthly_rows = report['monthly_rows']
    assert len(monthly_rows) == 2
    assert monthly_rows[0]['month_key'] == '2025-04'
    assert monthly_rows[0]['miles'] == 20

    vehicle_rows = report['vehicle_rows']
    assert len(vehicle_rows) == 2

    detail_headers, detail_rows = WorkExpenseMileageService.csv_rows(report, 'detail')
    assert detail_headers[0] == 'Date'
    assert len(detail_rows) == 3

    monthly_headers, monthly_csv_rows = WorkExpenseMileageService.csv_rows(report, 'monthly')
    assert monthly_headers[0] == 'Month'
    assert len(monthly_csv_rows) == 2
