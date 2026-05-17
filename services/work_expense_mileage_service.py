from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from models.expenses import Expense
from utils.db_helpers import family_query


class WorkExpenseMileageService:
    """Builds mileage review datasets for the Work Expenses section."""

    TWO_DP = Decimal("0.01")

    @staticmethod
    def current_finance_year(today: date | None = None) -> str:
        today = today or date.today()
        if today.month >= 4:
            return f"{today.year}-{today.year + 1}"
        return f"{today.year - 1}-{today.year}"

    @staticmethod
    def parse_finance_year(finance_year: str) -> tuple[date, date]:
        if not finance_year or "-" not in finance_year:
            raise ValueError("Invalid finance year format")

        parts = finance_year.split("-")
        if len(parts) != 2:
            raise ValueError("Invalid finance year format")

        start_year = int(parts[0])
        end_year = int(parts[1])
        if end_year != start_year + 1:
            raise ValueError("Invalid finance year range")

        return date(start_year, 4, 1), date(end_year, 3, 31)

    @staticmethod
    def available_finance_years() -> list[str]:
        years = (
            family_query(Expense)
            .filter(Expense.covered_miles.isnot(None), Expense.finance_year.isnot(None))
            .with_entities(Expense.finance_year)
            .distinct()
            .all()
        )
        values = sorted({y[0] for y in years if y[0]}, reverse=True)
        if not values:
            values.append(WorkExpenseMileageService.current_finance_year())
        return values

    @staticmethod
    def mileage_expenses(finance_year: str, vehicle_registration: str | None = None) -> list[Expense]:
        start_date, end_date = WorkExpenseMileageService.parse_finance_year(finance_year)
        query = family_query(Expense).filter(
            Expense.date >= start_date,
            Expense.date <= end_date,
            Expense.covered_miles.isnot(None),
            Expense.covered_miles > 0,
        )
        if vehicle_registration:
            query = query.filter(Expense.vehicle_registration == vehicle_registration)

        return query.order_by(Expense.date.asc(), Expense.id.asc()).all()

    @staticmethod
    def expense_miles(expense: Expense) -> int:
        miles = int(expense.covered_miles or 0)
        days = int(expense.days or 1)
        return miles * max(days, 1)

    @staticmethod
    def expense_amount(expense: Expense) -> Decimal:
        if expense.total_cost is not None:
            return Decimal(str(expense.total_cost)).quantize(WorkExpenseMileageService.TWO_DP)

        miles = Decimal(WorkExpenseMileageService.expense_miles(expense))
        rate = Decimal(str(expense.rate_per_mile or 0))
        return (miles * rate).quantize(WorkExpenseMileageService.TWO_DP, rounding=ROUND_HALF_UP)

    @staticmethod
    def month_key(d: date) -> str:
        return d.strftime("%Y-%m")

    @staticmethod
    def month_label(month_key: str) -> str:
        return datetime.strptime(month_key, "%Y-%m").strftime("%b %Y")

    @staticmethod
    def _summarize_rows(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            miles = row.get("miles", 0)
            amount = Decimal(str(row.get("amount", 0)))
            row["avg_rate"] = float((amount / Decimal(miles)).quantize(WorkExpenseMileageService.TWO_DP)) if miles else 0.0
            row["amount"] = float(amount.quantize(WorkExpenseMileageService.TWO_DP))

    @staticmethod
    def build_report(expenses: list[Expense], finance_year: str) -> dict[str, Any]:
        start_date, end_date = WorkExpenseMileageService.parse_finance_year(finance_year)

        totals = {
            "entries": 0,
            "miles": 0,
            "amount": Decimal("0.00"),
            "vehicles": set(),
        }

        monthly: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "month_key": "",
            "month_label": "",
            "entries": 0,
            "miles": 0,
            "amount": Decimal("0.00"),
        })

        by_vehicle: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "vehicle": "Unassigned",
            "entries": 0,
            "miles": 0,
            "amount": Decimal("0.00"),
        })

        rate_bands: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "rate": Decimal("0.00"),
            "entries": 0,
            "miles": 0,
            "amount": Decimal("0.00"),
            "first_date": None,
            "last_date": None,
        })

        detailed_rows: list[dict[str, Any]] = []

        for exp in expenses:
            miles = WorkExpenseMileageService.expense_miles(exp)
            amount = WorkExpenseMileageService.expense_amount(exp)
            month_key = WorkExpenseMileageService.month_key(exp.date)
            vehicle = exp.vehicle_registration or "Unassigned"
            rate = Decimal(str(exp.rate_per_mile or 0)).quantize(WorkExpenseMileageService.TWO_DP)
            rate_key = f"{rate:.2f}"

            totals["entries"] += 1
            totals["miles"] += miles
            totals["amount"] += amount
            totals["vehicles"].add(vehicle)

            m = monthly[month_key]
            m["month_key"] = month_key
            m["month_label"] = WorkExpenseMileageService.month_label(month_key)
            m["entries"] += 1
            m["miles"] += miles
            m["amount"] += amount

            v = by_vehicle[vehicle]
            v["vehicle"] = vehicle
            v["entries"] += 1
            v["miles"] += miles
            v["amount"] += amount

            rb = rate_bands[rate_key]
            rb["rate"] = rate
            rb["entries"] += 1
            rb["miles"] += miles
            rb["amount"] += amount
            rb["first_date"] = exp.date if rb["first_date"] is None else min(rb["first_date"], exp.date)
            rb["last_date"] = exp.date if rb["last_date"] is None else max(rb["last_date"], exp.date)

            detailed_rows.append(
                {
                    "id": exp.id,
                    "date": exp.date,
                    "description": exp.description,
                    "vehicle": vehicle,
                    "covered_miles": int(exp.covered_miles or 0),
                    "days": int(exp.days or 1),
                    "miles": miles,
                    "rate": float(rate),
                    "amount": float(amount),
                    "submitted": bool(exp.submitted),
                    "reimbursed": bool(exp.reimbursed),
                }
            )

        monthly_rows = sorted(monthly.values(), key=lambda r: r["month_key"])
        vehicle_rows = sorted(by_vehicle.values(), key=lambda r: r["vehicle"])
        rate_rows = sorted(rate_bands.values(), key=lambda r: (r["first_date"] or start_date, r["rate"]))

        WorkExpenseMileageService._summarize_rows(monthly_rows)
        WorkExpenseMileageService._summarize_rows(vehicle_rows)

        for row in rate_rows:
            miles = row.get("miles", 0)
            amount = Decimal(str(row.get("amount", 0)))
            row["amount"] = float(amount.quantize(WorkExpenseMileageService.TWO_DP))
            row["avg_rate"] = float((amount / Decimal(miles)).quantize(WorkExpenseMileageService.TWO_DP)) if miles else 0.0
            row["rate"] = float(Decimal(str(row["rate"])).quantize(WorkExpenseMileageService.TWO_DP))

        total_amount = totals["amount"].quantize(WorkExpenseMileageService.TWO_DP)
        avg_rate = (total_amount / Decimal(totals["miles"])).quantize(WorkExpenseMileageService.TWO_DP) if totals["miles"] else Decimal("0.00")

        summary = {
            "finance_year": finance_year,
            "start_date": start_date,
            "end_date": end_date,
            "entries": totals["entries"],
            "miles": totals["miles"],
            "amount": float(total_amount),
            "vehicle_count": len(totals["vehicles"]),
            "avg_rate": float(avg_rate),
        }

        return {
            "summary": summary,
            "monthly_rows": monthly_rows,
            "vehicle_rows": vehicle_rows,
            "rate_rows": rate_rows,
            "detailed_rows": detailed_rows,
        }

    @staticmethod
    def csv_rows(report: dict[str, Any], export_type: str) -> tuple[list[str], list[list[Any]]]:
        if export_type == "monthly":
            headers = ["Month", "Entries", "Miles", "Amount", "Average Rate"]
            rows = [
                [r["month_label"], r["entries"], r["miles"], f"{r['amount']:.2f}", f"{r['avg_rate']:.2f}"]
                for r in report["monthly_rows"]
            ]
            return headers, rows

        if export_type == "yearly":
            headers = ["Vehicle", "Entries", "Miles", "Amount", "Average Rate"]
            rows = [
                [r["vehicle"], r["entries"], r["miles"], f"{r['amount']:.2f}", f"{r['avg_rate']:.2f}"]
                for r in report["vehicle_rows"]
            ]
            return headers, rows

        headers = [
            "Date",
            "Description",
            "Vehicle",
            "Covered Miles",
            "Days",
            "Claim Miles",
            "Rate Per Mile",
            "Amount",
            "Submitted",
            "Reimbursed",
        ]
        rows = [
            [
                r["date"].isoformat(),
                r["description"],
                r["vehicle"],
                r["covered_miles"],
                r["days"],
                r["miles"],
                f"{r['rate']:.2f}",
                f"{r['amount']:.2f}",
                "Yes" if r["submitted"] else "No",
                "Yes" if r["reimbursed"] else "No",
            ]
            for r in report["detailed_rows"]
        ]
        return headers, rows
