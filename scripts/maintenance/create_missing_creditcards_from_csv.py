"""
Create missing `CreditCard` records for card names found in CSV (excluding 'Nationwide').
Usage:
    python -m scripts.maintenance.create_missing_creditcards_from_csv scripts/data/expenses_ACTUAL.csv

Default values:
- annual_apr and monthly_apr set to 0.00
- credit_limit set to 1000.00
"""
import sys
import csv
from collections import Counter

from app import create_app
from extensions import db
from models.credit_cards import CreditCard


def main(csv_path):
    app = create_app()
    app.app_context().push()

    cards = Counter()
    with open(csv_path, newline='', encoding='utf-8-sig') as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            card = (row.get('Card') or row.get('card') or '').strip()
            if card and 'nationwide' not in card.lower():
                cards[card]+=1

    created = 0
    for name,count in cards.most_common():
        existing = CreditCard.query.filter(CreditCard.card_name.ilike(f"%{name}%")).first()
        if existing:
            continue
        cc = CreditCard(
            card_name=name,
            annual_apr=0.00,
            monthly_apr=0.00,
            credit_limit=1000.00
        )
        db.session.add(cc)
        created += 1
        print(f'Creating CreditCard: {name} (sample rows: {count})')

    if created:
        db.session.commit()
    print(f'Created {created} credit card(s)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.maintenance.create_missing_creditcards_from_csv path/to/file.csv')
        sys.exit(1)
    main(sys.argv[1])
