"""
Check credit card regeneration logic
"""
from app import create_app
from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from services.credit_card_service import CreditCardService
from datetime import date
from dateutil.relativedelta import relativedelta

app = create_app()

with app.app_context():
    # Get first active card
    card = CreditCard.query.filter_by(is_active=True).first()
    
    if not card:
        print("No active cards found")
        exit()
    
    print(f"\n{'='*80}")
    print(f"Testing Credit Card: {card.card_name}")
    print(f"{'='*80}")
    print(f"Credit Limit: £{card.credit_limit}")
    print(f"Set Payment: £{card.set_payment}")
    print(f"Current Balance (paid only): £{card.current_balance}")
    print(f"Available Credit: £{card.available_credit}")
    
    # Get all transactions
    transactions = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id
    ).order_by(CreditCardTransaction.date.asc()).all()
    
    print(f"\nTotal Transactions: {len(transactions)}")
    
    # Show last 10 transactions
    print(f"\nLast 10 Transactions:")
    print(f"{'Date':<12} {'Type':<12} {'Amount':>10} {'Balance':>10} {'Paid':<6}")
    print("-" * 60)
    
    for txn in transactions[-10:]:
        print(f"{txn.date.strftime('%Y-%m-%d'):<12} "
              f"{txn.transaction_type:<12} "
              f"£{txn.amount:>9.2f} "
              f"£{txn.balance:>9.2f} "
              f"{'Yes' if txn.is_paid else 'No':<6}")
    
    # Check if payment brings balance to 0
    print(f"\n{'='*80}")
    print("Checking Statement/Payment Logic:")
    print(f"{'='*80}")
    
    # Find latest statement and payment pair
    statements = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id,
        transaction_type='Interest'
    ).order_by(CreditCardTransaction.date.desc()).limit(3).all()
    
    for stmt in statements:
        print(f"\nStatement Date: {stmt.date}")
        print(f"  Statement Amount: £{stmt.amount:.2f}")
        print(f"  Balance After Interest: £{stmt.balance:.2f}")
        
        # Find payment for this statement (14 days later typically)
        payment_date = stmt.date + relativedelta(days=14)
        payment = CreditCardTransaction.query.filter_by(
            credit_card_id=card.id,
            date=payment_date,
            transaction_type='Payment'
        ).first()
        
        if payment:
            print(f"  Payment Date: {payment.date}")
            print(f"  Payment Amount: £{payment.amount:.2f}")
            print(f"  Balance After Payment: £{payment.balance:.2f}")
            
            # Check if payment equals balance before payment
            if abs(payment.amount + stmt.balance) < 0.01:  # Should be close to 0
                print(f"  ✓ Payment correctly pays off balance!")
            else:
                print(f"  ✗ Payment does NOT pay off balance")
                print(f"     Expected payment: £{abs(stmt.balance):.2f}")
                print(f"     Actual payment: £{payment.amount:.2f}")
                print(f"     Difference: £{abs(payment.amount - abs(stmt.balance)):.2f}")
        else:
            print(f"  No payment found for {payment_date}")
