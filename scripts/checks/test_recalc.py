"""
Test recalculate logic on a card
"""
from app import create_app
from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction

app = create_app()

with app.app_context():
    card = CreditCard.query.filter_by(card_name='Natwest').first()
    
    if not card:
        print("Card not found")
        exit()
    
    print(f"Card: {card.card_name}")
    print(f"Before recalculate:")
    print(f"  Current Balance: £{card.current_balance}")
    
    # Get all transactions
    txns = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id
    ).order_by(CreditCardTransaction.date.asc()).all()
    
    print(f"\nTransactions (before recalc):")
    for txn in txns[-5:]:
        print(f"  {txn.date} {txn.transaction_type:12} {txn.amount:>10.2f} -> Balance: {txn.balance:>10.2f} (Paid: {txn.is_paid})")
    
    # Recalculate
    print(f"\nRecalculating...")
    CreditCardTransaction.recalculate_card_balance(card.id)
    
    # Check in-memory first (don't requery)
    print(f"\nAfter recalculate (in-memory check):")
    for txn in txns[-5:]:
        print(f"  {txn.date} {txn.transaction_type:12} {txn.amount:>10.2f} -> Balance: {txn.balance:>10.2f} (Paid: {txn.is_paid})")
    
    # Refresh from database
    db.session.expire_all()
    card = CreditCard.query.filter_by(card_name='Natwest').first()
    txns = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id
    ).order_by(CreditCardTransaction.date.asc()).all()
    
    print(f"\nAfter recalculate (requeried from DB):")
    print(f"  Current Balance: £{card.current_balance}")
    
    print(f"\nTransactions (after recalc):")
    for txn in txns[-5:]:
        print(f"  {txn.date} {txn.transaction_type:12} {txn.amount:>10.2f} -> Balance: {txn.balance:>10.2f} (Paid: {txn.is_paid})")
    
    # Manual calculation
    print(f"\nManual calculation:")
    running = 0.0
    for txn in txns:
        running += float(txn.amount)
        print(f"  {txn.date} {txn.transaction_type:12} {txn.amount:>10.2f} -> Running: {running:>10.2f}")
