"""
Import credit cards - TEMPLATE
⚠️ WARNING: This is a template with placeholder values
Copy this file to import_credit_cards_ACTUAL.py and fill in your real data
The _ACTUAL.py file is gitignored for security
"""
import sys
import os
from datetime import date

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import CreditCard

# Credit card data - TEMPLATE WITH PLACEHOLDER VALUES
# ⚠️ DO NOT commit real financial data to Git!
# Copy this file to import_credit_cards_ACTUAL.py and fill in real values
CREDIT_CARDS = [
    # Active Cards
    {
        'card_name': 'Card 1',
        'annual_apr': 0.00,  # TODO: Update with actual APR
        'monthly_apr': 0.00,  # TODO: Update with actual monthly APR
        'min_payment_percent': 3.00,
        'credit_limit': 0.00,  # TODO: Update with actual limit
        'set_payment': 0.00,  # TODO: Update with actual payment
        'statement_date': 1,
        'current_balance': 0.00,  # TODO: Update with actual balance (negative = owe money)
        'start_date': None,
        'is_active': True
    },
    # Add more cards as needed...
]


def import_credit_cards():
    """Import all credit cards into database"""
    app = create_app()
    
    with app.app_context():
        print("Starting credit card import...")
        print(f"Total cards to import: {len(CREDIT_CARDS)}")
        print("-" * 50)
        
        imported_count = 0
        skipped_count = 0
        
        for card_data in CREDIT_CARDS:
            # Check if card already exists
            existing = CreditCard.query.filter_by(card_name=card_data['card_name']).first()
            
            if existing:
                print(f"⏭️  Skipped: {card_data['card_name']} (already exists)")
                skipped_count += 1
                continue
            
            # Calculate available credit
            available_credit = card_data['credit_limit'] - abs(card_data['current_balance'])
            
            # Create new credit card
            card = CreditCard(
                card_name=card_data['card_name'],
                annual_apr=card_data['annual_apr'],
                monthly_apr=card_data['monthly_apr'],
                min_payment_percent=card_data['min_payment_percent'],
                credit_limit=card_data['credit_limit'],
                set_payment=card_data['set_payment'],
                statement_date=card_data['statement_date'],
                current_balance=card_data['current_balance'],
                available_credit=available_credit,
                start_date=card_data['start_date'],
                is_active=card_data['is_active']
            )
            
            db.session.add(card)
            imported_count += 1
            
            # Show status
            status_emoji = "💳" if card_data['is_active'] else "❌"
            balance_str = f"£{abs(card_data['current_balance']):.2f}" if card_data['current_balance'] != 0 else "£0.00"
            print(f"{status_emoji} Added: {card_data['card_name']} - Balance: {balance_str} ({'Active' if card_data['is_active'] else 'Closed'})")
        
        # Commit all cards
        db.session.commit()
        
        print("-" * 50)
        print(f"✅ Import complete!")
        print(f"   Imported: {imported_count} cards")
        print(f"   Skipped: {skipped_count} cards")
        print(f"   Total in database: {CreditCard.query.count()} cards")
        
        # Show summary
        active_count = CreditCard.query.filter_by(is_active=True).count()
        inactive_count = CreditCard.query.filter_by(is_active=False).count()
        print(f"\n📊 Summary:")
        print(f"   Active cards: {active_count}")
        print(f"   Closed cards: {inactive_count}")


if __name__ == '__main__':
    import_credit_cards()
