"""Print active credit-card promotional APR periods from the configured database."""
from datetime import date

from app import create_app
from models.credit_cards import CreditCard


app = create_app()

with app.app_context():
    cards = CreditCard.query.filter_by(is_active=True).all()
    test_date = date(2026, 6, 1)
    today = date.today()

    print("=" * 70)
    print("CREDIT CARD 0% PROMOTIONAL PERIODS")
    print("=" * 70)

    for card in cards:
        print(f"\n{card.card_name}:")
        print(f"  Standard APR: {card.monthly_apr}%")

        if card.purchase_0_percent_until:
            print(f"  0% Purchases until: {card.purchase_0_percent_until}")
            status = "ACTIVE" if today <= card.purchase_0_percent_until else "EXPIRED"
            print(f"    {status}")
            print(f"  APR on {test_date}: {card.get_current_purchase_apr(test_date)}%")
        else:
            print("  0% Purchases: None set")

        if card.balance_transfer_0_percent_until:
            print(f"  0% Balance Transfer until: {card.balance_transfer_0_percent_until}")
            status = "ACTIVE" if today <= card.balance_transfer_0_percent_until else "EXPIRED"
            print(f"    {status}")
        else:
            print("  0% Balance Transfer: None set")

    print("\n" + "=" * 70)