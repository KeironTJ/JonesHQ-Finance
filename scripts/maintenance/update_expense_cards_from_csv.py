"""
Update `Expense.credit_card_id` from CSV `Card` values.
Usage:
    python -m scripts.maintenance.update_expense_cards_from_csv scripts/data/expenses_ACTUAL.csv

Behavior:
- For rows where Card contains 'Nationwide' (case-insensitive), we treat them as bank transactions and DO NOT set `credit_card_id`.
- For other Card values, we try to find a `CreditCard` whose `card_name` matches (case-insensitive substring) and set `expense.credit_card_id` accordingly.
- Matches are attempted by `date` + `total_cost` and description substring when available.
"""
import sys
import csv
from datetime import datetime
from decimal import Decimal

from app import create_app
from extensions import db
from models.expenses import Expense
from models.credit_cards import CreditCard


def find_expense(dt, total_cost, description):
    # Try date + amount + description match
    q = Expense.query.filter_by(date=dt, total_cost=total_cost)
    if description:
        q = q.filter(Expense.description.ilike(f"%{description}%"))
    exp = q.first()
    if exp:
        return exp
    # Fallback: date + amount only
    return Expense.query.filter_by(date=dt, total_cost=total_cost).first()


def main(csv_path):
    app = create_app()
    app.app_context().push()

    updated = 0
    not_found = 0
    no_card = 0
    no_creditcard_match = 0

    with open(csv_path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            r = {k.strip(): v.strip() if v is not None else None for k, v in row.items()}
            date_str = r.get('Date') or r.get('date')
            if not date_str:
                continue
            try:
                dt = datetime.strptime(date_str, '%d/%m/%Y').date()
            except Exception:
                try:
                    dt = datetime.strptime(date_str, '%Y-%m-%d').date()
                except Exception:
                    continue

            tc = r.get('Total Cost') or r.get('TotalCost') or r.get('total_cost')
            if not tc:
                continue
            try:
                total_cost = Decimal(tc.replace('£', '').replace('Â', '').strip())
            except Exception:
                continue

            card_name = (r.get('Card') or r.get('card') or '').strip()
            description = (r.get('Description') or r.get('description') or '').strip()

            exp = find_expense(dt, total_cost, description)
            if not exp:
                not_found += 1
                continue

            if not card_name:
                no_card += 1
                continue

            if 'nationwide' in card_name.lower():
                # Treat as bank account; ensure credit_card_id is NULL
                if exp.credit_card_id is not None:
                    exp.credit_card_id = None
                    db.session.add(exp)
                    updated += 1
                continue

            # Find credit card by name
            cc = CreditCard.query.filter(CreditCard.card_name.ilike(f"%{card_name}%")).first()
            if not cc:
                no_creditcard_match += 1
                continue

            if exp.credit_card_id != cc.id:
                exp.credit_card_id = cc.id
                db.session.add(exp)
                updated += 1

    db.session.commit()
    print(f'Updated: {updated}')
    print(f'Not found: {not_found}')
    print(f'No card specified in CSV: {no_card}')
    print(f'No matching CreditCard record found: {no_creditcard_match}')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.maintenance.update_expense_cards_from_csv path/to/file.csv')
        sys.exit(1)
    main(sys.argv[1])
