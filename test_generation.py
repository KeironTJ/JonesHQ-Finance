"""Recalculate card balances and test generation with fixed payment sign"""
from datetime import date
from app import create_app
from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from services.credit_card_service import CreditCardService

app = create_app()

with app.app_context():
    print("=" * 70)
    print("RECALCULATING CARD BALANCES")
    print("=" * 70)
    
    cards = CreditCard.query.filter_by(is_active=True).all()
    for card in cards:
        print(f"\nRecalculating {card.card_name}...")
        CreditCardTransaction.recalculate_card_balance(card.id)
        db.session.commit()
        
        updated = CreditCard.query.get(card.id)
        print(f"  Current balance: £{updated.current_balance:,.2f}")
    
    print("\n" + "=" * 70)
    print("TESTING GENERATION WITH FIXED PAYMENT SIGN")
    print("=" * 70)
    
    # Generate for Feb-Dec 2026
    result = CreditCardService.generate_all_monthly_statements(
        start_date=date(2026, 2, 1),
        end_date=date(2026, 12, 31),
        payment_offset_days=14
    )
    
    print("\n" + "=" * 70)
    print("GENERATION RESULTS")
    print("=" * 70)
    print(f"Cards processed: {result['cards_processed']}")
    print(f"Statements created: {result['statements_created']}")
    print(f"Payments created: {result['payments_created']}")
    print(f"Zero-balance statements: {result['zero_balance_statements']}")
    
    # Show final balances
    print("\n" + "=" * 70)
    print("FINAL CARD BALANCES (after generation)")
    print("=" * 70)
    
    for card_name in ['Natwest', 'M&S', 'Barclaycard']:
        card = CreditCard.query.filter_by(card_name=card_name).first()
        if card:
            print(f"\n{card_name}:")
            print(f"  Starting balance: £-1,815.46" if card_name == 'Barclaycard' else (f"  Starting balance: £-6,210.20" if card_name == 'M&S' else "  Starting balance: £0.00"))
            print(f"  Final balance: £{card.current_balance:,.2f}")
            
            if card.current_balance:
                owed = abs(float(card.current_balance))
                print(f"  Amount owed: £{owed:,.2f}")
                
                # Show if debt decreased
                if card_name == 'Barclaycard':
                    original = 1815.46
                    if owed < original:
                        print(f"  ✅ Debt DECREASED by £{original - owed:,.2f}")
                    else:
                        print(f"  ❌ Debt INCREASED by £{owed - original:,.2f}")
                elif card_name == 'M&S':
                    original = 6210.20
                    if owed < original:
                        print(f"  ✅ Debt DECREASED by £{original - owed:,.2f}")
                    else:
                        print(f"  ❌ Debt INCREASED by £{owed - original:,.2f}")
