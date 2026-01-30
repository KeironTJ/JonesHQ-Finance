from app import create_app
from models.credit_cards import CreditCard
import csv
from collections import Counter

app = create_app()
app.app_context().push()

cards = Counter()
with open('scripts/data/expenses_ACTUAL.csv', newline='', encoding='utf-8-sig') as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        card = (row.get('Card') or row.get('card') or '').strip()
        if card:
            cards[card]+=1

# Check which card names have matches
unmatched = []
for name,count in cards.most_common():
    cc = CreditCard.query.filter(CreditCard.card_name.ilike(f"%{name}%")).first()
    if not cc:
        unmatched.append((name,count))

print('Unmatched card names:')
for name,count in unmatched:
    print(f"{name}: {count}")
