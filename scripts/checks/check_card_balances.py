from app import create_app
from extensions import db
from models import CreditCard, CreditCardTransaction

app = create_app()

with app.app_context():
    cards = CreditCard.query.all()
    
    for card in cards:
        print(f"\n{card.card_name}:")
        print(f"  Current Balance (stored): £{card.current_balance}")
        print(f"  Available Credit (stored): £{card.available_credit}")
        print(f"  Credit Limit: £{card.credit_limit}")
        
        # Count transactions
        txn_count = CreditCardTransaction.query.filter_by(credit_card_id=card.id).count()
        print(f"  Total Transactions: {txn_count}")
        
        # Get latest transaction
        latest = CreditCardTransaction.query.filter_by(
            credit_card_id=card.id
        ).order_by(CreditCardTransaction.date.desc()).first()
        
        if latest:
            print(f"  Latest Transaction: {latest.date} - {latest.item}")
            print(f"  Latest Balance: £{latest.balance}")
            print(f"  Latest Available: £{latest.credit_available}")
        
        # Recalculate
        print(f"\n  Recalculating...")
        CreditCardTransaction.recalculate_card_balance(card.id)
        
        # Refresh card
        db.session.refresh(card)
        print(f"  New Balance: £{card.current_balance}")
        print(f"  New Available: £{card.available_credit}")
