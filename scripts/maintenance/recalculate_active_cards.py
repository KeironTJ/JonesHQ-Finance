from app import create_app
from extensions import db
from models import CreditCard, CreditCardTransaction

app = create_app()

with app.app_context():
    active_cards = CreditCard.query.filter_by(is_active=True).all()
    
    print(f"Recalculating {len(active_cards)} active cards\n")
    
    for card in active_cards:
        print(f"{card.card_name}:")
        print(f"  Before: Balance=£{card.current_balance}, Available=£{card.available_credit}")
        
        CreditCardTransaction.recalculate_card_balance(card.id)
        
        # Refresh to get updated values
        db.session.refresh(card)
        
        print(f"  After: Balance=£{card.current_balance}, Available=£{card.available_credit}\n")
    
    print("All active cards recalculated successfully!")
