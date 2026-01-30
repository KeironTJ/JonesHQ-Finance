"""
Script: Import work expenses from CSV into Expense model.
Usage:
    python -m scripts.maintenance.import_work_expenses path/to/file.csv

CSV expected columns (case-insensitive):
Date, Month, Week, Description, Type, Card, Covered Miles, Rate / Cost, Days, Total Cost, Paid For, Submitted, Reimbursed, VRN, Day, Finance Year, Cumulative Miles YTD

This script will create `Expense` records. Fuel expenses will be imported but will NOT automatically create `FuelRecord`/`Trip` or transactions yet.
"""
import sys
import csv
from datetime import datetime
from decimal import Decimal

from app import create_app
from extensions import db
from models.expenses import Expense
from models.credit_cards import CreditCard
from models.vehicles import Vehicle


def parse_bool(value):
    if value is None:
        return False
    v = str(value).strip().lower()
    return v in ('1', 'true', 'yes', 'y', 't')


def main(csv_path):
    app = create_app()
    app.app_context().push()

    created = 0
    with open(csv_path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            # Normalize keys
            r = {k.strip(): v.strip() if v is not None else None for k, v in row.items()}

            # Parse date
            date_str = r.get('Date') or r.get('date')
            if not date_str:
                print('Skipping row with no Date')
                continue
            try:
                dt = datetime.strptime(date_str, '%d/%m/%Y').date()
            except Exception:
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d').date()
                except Exception:
                    print(f'Could not parse date: {date_str} - skipping')
                    continue

            description = r.get('Description') or r.get('description') or ''
            expense_type = r.get('Type') or r.get('type') or ''

            card_name = r.get('Card') or r.get('card') or ''
            credit_card = None
            if card_name:
                credit_card = CreditCard.query.filter(CreditCard.card_name.ilike(f"%{card_name}%")).first()

            covered_miles = None
            try:
                cm = r.get('Covered Miles') or r.get('CoveredMiles') or r.get('covered_miles')
                covered_miles = int(cm) if cm else None
            except Exception:
                covered_miles = None

            rate = None
            try:
                rate_str = r.get('Rate / Cost') or r.get('Rate / Cost'.strip()) or r.get('Rate')
                if rate_str:
                    # remove currency symbols
                    rate = Decimal(rate_str.replace('£', '').replace('Â', '').strip())
            except Exception:
                rate = None

            days = None
            try:
                days = int(r.get('Days') or r.get('days') or 1)
            except Exception:
                days = 1

            total_cost = Decimal('0')
            try:
                tc = r.get('Total Cost') or r.get('TotalCost') or r.get('total_cost')
                if tc:
                    total_cost = Decimal(tc.replace('£', '').replace('Â', '').strip())
            except Exception:
                total_cost = Decimal('0')

            paid_for = parse_bool(r.get('Paid For') or r.get('PaidFor') or r.get('paid_for'))
            submitted = parse_bool(r.get('Submitted') or r.get('submitted'))
            reimbursed = parse_bool(r.get('Reimbursed') or r.get('reimbursed'))

            vrn = r.get('VRN') or r.get('vrn') or r.get('Vehicle') or r.get('vehicle')
            finance_year = r.get('Finance Year') or r.get('FinanceYear') or ''
            cumulative_miles_ytd = None
            try:
                cm_ytd = r.get('Cumulative Miles YTD') or r.get('CumulativeMilesYTD')
                if cm_ytd:
                    cumulative_miles_ytd = int(cm_ytd)
            except Exception:
                cumulative_miles_ytd = None

            expense = Expense(
                date=dt,
                month=(r.get('Month') or '').strip() or None,
                week=(r.get('Week') or '').strip() or None,
                day_name=(r.get('Day') or '').strip() or None,
                finance_year=finance_year,
                description=description,
                expense_type=expense_type,
                credit_card_id=credit_card.id if credit_card else None,
                covered_miles=covered_miles,
                rate_per_mile=rate,
                days=days,
                cumulative_miles_ytd=cumulative_miles_ytd,
                vehicle_registration=vrn,
                cost=total_cost,
                total_cost=total_cost,
                paid_for=paid_for,
                submitted=submitted,
                reimbursed=reimbursed
            )

            db.session.add(expense)
            created += 1

        db.session.commit()
    print(f'Imported {created} expense rows')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python import_work_expenses.py path/to/file.csv')
        sys.exit(1)
    main(sys.argv[1])
