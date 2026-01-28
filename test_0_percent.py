"""Test 0% promotional period logic"""
from datetime import date
from app import create_app
from models.credit_cards import CreditCard

app = create_app()

with app.app_context():
    cards = CreditCard.query.filter_by(is_active=True).all()
    
    print("=" * 70)
    print("CREDIT CARD 0% PROMOTIONAL PERIODS")
    print("=" * 70)
    
    test_date = date(2026, 6, 1)  # Test date in June 2026
    today = date.today()
    
    for card in cards:
        print(f"\n{card.card_name}:")
        print(f"  Standard APR: {card.monthly_apr}%")
        
        if card.purchase_0_percent_until:
            print(f"  0% Purchases until: {card.purchase_0_percent_until}")
            if today <= card.purchase_0_percent_until:
                print(f"    ✅ ACTIVE (ends in {(card.purchase_0_percent_until - today).days} days)")
            else:
                print(f"    ❌ EXPIRED")
            
            # Test APR on test date
            apr_on_test = card.get_current_purchase_apr(test_date)
            print(f"  APR on {test_date}: {apr_on_test}%")
        else:
            print(f"  0% Purchases: None set")
            
        if card.balance_transfer_0_percent_until:
            print(f"  0% Balance Transfer until: {card.balance_transfer_0_percent_until}")
            if today <= card.balance_transfer_0_percent_until:
                print(f"    ✅ ACTIVE")
            else:
                print(f"    ❌ EXPIRED")
        else:
            print(f"  0% Balance Transfer: None set")
    
    print("\n" + "=" * 70)
    print("If the dates show 'None set', you need to edit the card and add the")
    print("promotional end dates in the UI.")
    print("=" * 70)
