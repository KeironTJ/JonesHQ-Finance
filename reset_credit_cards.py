"""Reset credit card data and reimport"""
from app import create_app
from extensions import db
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard

app = create_app()

with app.app_context():
    print("=" * 70)
    print("DELETING ALL CREDIT CARD TRANSACTIONS")
    print("=" * 70)
    
    # Delete all credit card transactions
    deleted = CreditCardTransaction.query.delete()
    db.session.commit()
    
    print(f"✅ Deleted {deleted} credit card transactions")
    
    # Reset card balances to zero
    print("\n" + "=" * 70)
    print("RESETTING CARD BALANCES")
    print("=" * 70)
    
    cards = CreditCard.query.all()
    for card in cards:
        card.current_balance = 0.0
        card.available_credit = float(card.credit_limit)
    
    db.session.commit()
    
    print(f"✅ Reset {len(cards)} credit card balances to £0.00")
    
    print("\n" + "=" * 70)
    print("NOW RUN: python scripts/import_credit_card_transactions.py")
    print("=" * 70)
