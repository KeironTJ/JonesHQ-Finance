"""
Import credit cards
Run this script to populate the credit_cards table
"""
import sys
import os
from datetime import date

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import CreditCard

# Credit card data from Excel
CREDIT_CARDS = [
    # Active Cards
    {
        'card_name': 'Natwest',
        'annual_apr': 26.44,
        'monthly_apr': 2.20,
        'min_payment_percent': 1.00,
        'credit_limit': 10000.00,
        'set_payment': 200.00,
        'statement_date': 3,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': True
    },
    {
        'card_name': 'M&S',
        'annual_apr': 28.90,
        'monthly_apr': 2.41,
        'min_payment_percent': 1.00,
        'credit_limit': 7200.00,
        'set_payment': 200.00,
        'statement_date': 15,
        'current_balance': -6253.39,  # Negative = owe money
        'start_date': None,
        'is_active': True
    },
    {
        'card_name': 'Barclaycard',
        'annual_apr': 22.44,
        'monthly_apr': 1.87,
        'min_payment_percent': 1.00,
        'credit_limit': 3500.00,
        'set_payment': 200.00,
        'statement_date': 8,
        'current_balance': -1815.46,  # Negative = owe money
        'start_date': date(2025, 8, 25),
        'is_active': True
    },
    
    # Inactive Cards (closed)
    {
        'card_name': 'Vanquis',
        'annual_apr': 37.68,
        'monthly_apr': 3.14,
        'min_payment_percent': 1.00,
        'credit_limit': 6000.00,
        'set_payment': 50.00,
        'statement_date': 17,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Aqua',
        'annual_apr': 36.29,
        'monthly_apr': 3.02,
        'min_payment_percent': 1.00,
        'credit_limit': 2300.00,
        'set_payment': 100.00,
        'statement_date': 15,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Capital One',
        'annual_apr': 34.94,
        'monthly_apr': 2.91,
        'min_payment_percent': 3.91,
        'credit_limit': 0.00,  # No limit recorded
        'set_payment': 200.00,
        'statement_date': 7,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Zopa',
        'annual_apr': 31.15,
        'monthly_apr': 2.60,
        'min_payment_percent': 2.70,
        'credit_limit': 1250.00,
        'set_payment': 100.00,
        'statement_date': 9,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Jaja',
        'annual_apr': 27.39,
        'monthly_apr': 2.28,
        'min_payment_percent': 1.00,
        'credit_limit': 3200.00,
        'set_payment': 200.00,
        'statement_date': 15,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Zable',
        'annual_apr': 27.39,
        'monthly_apr': 2.28,
        'min_payment_percent': 1.00,
        'credit_limit': 1500.00,
        'set_payment': 125.00,
        'statement_date': 15,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Marbles',
        'annual_apr': 27.39,
        'monthly_apr': 2.28,
        'min_payment_percent': 1.00,
        'credit_limit': 8000.00,
        'set_payment': 100.00,
        'statement_date': 7,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
    {
        'card_name': 'Capital One2',
        'annual_apr': 34.94,
        'monthly_apr': 2.91,
        'min_payment_percent': 3.91,
        'credit_limit': 0.00,
        'set_payment': 0.00,
        'statement_date': 28,
        'current_balance': 0.00,
        'start_date': None,
        'is_active': False
    },
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
