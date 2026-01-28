from app import create_app
from extensions import db
from models import CreditCard, CreditCardTransaction

app = create_app()

with app.app_context():
    cards = CreditCard.query.filter_by(is_active=True).all()
    
    print(f"Active cards: {len(cards)}\n")
    
    for card in cards:
        print(f"{card.card_name} (ID: {card.id}):")
        print(f"  Active: {card.is_active}")
        print(f"  Current Balance: £{card.current_balance}")
        print(f"  Credit Limit: £{card.credit_limit}")
        
        txn_count = CreditCardTransaction.query.filter_by(credit_card_id=card.id).count()
        print(f"  Transactions: {txn_count}")
        
        latest = CreditCardTransaction.query.filter_by(
            credit_card_id=card.id
        ).order_by(CreditCardTransaction.date.desc()).first()
        
        if latest:
            print(f"  Latest: {latest.date} - {latest.item} - Balance: £{latest.balance}")
        print()
