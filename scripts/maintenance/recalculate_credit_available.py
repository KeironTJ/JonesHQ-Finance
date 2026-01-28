"""
Recalculate available credit for all credit card transactions.

This fixes the available_credit values that were calculated with the old (incorrect) formula.
The old formula was: credit_limit - running_balance
Which gave wrong results when balance was negative (owing money).

The new formula is: credit_limit - abs(running_balance)
Which correctly calculates available credit.
"""

from app import create_app, db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction

def main():
    app = create_app()
    
    with app.app_context():
        # Get all active credit cards
        cards = CreditCard.query.filter_by(is_active=True).all()
        
        print(f"Found {len(cards)} active credit cards")
        print("-" * 60)
        
        total_transactions_updated = 0
        
        for card in cards:
            print(f"\nRecalculating: {card.card_name}")
            print(f"  Credit Limit: £{card.credit_limit:,.2f}")
            print(f"  Old Available Credit: £{card.available_credit:,.2f}")
            
            # Get transaction count before
            txn_count = CreditCardTransaction.query.filter_by(credit_card_id=card.id).count()
            
            # Recalculate all balances and available credit
            CreditCardTransaction.recalculate_card_balance(card.id)
            db.session.commit()
            
            # Refresh card to get new available_credit
            db.session.refresh(card)
            
            print(f"  New Available Credit: £{card.available_credit:,.2f}")
            print(f"  Transactions Updated: {txn_count}")
            
            total_transactions_updated += txn_count
        
        print("\n" + "=" * 60)
        print(f"COMPLETE: Updated {total_transactions_updated} transactions across {len(cards)} cards")
        print("=" * 60)

if __name__ == "__main__":
    main()
