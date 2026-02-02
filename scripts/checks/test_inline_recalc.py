"""
Test recalculate inline
"""
from app import create_app
from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction

app = create_app()

with app.app_context():
    card = CreditCard.query.filter_by(card_name='Natwest').first()
    
    # Get all transactions
    transactions = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id
    ).order_by(CreditCardTransaction.date.asc()).all()
    
    print(f"Processing {len(transactions)} transactions")
    
    running_balance = 0.0
    for i, txn in enumerate(transactions):
        old_balance = txn.balance
        running_balance += float(txn.amount)
        txn.balance = round(running_balance, 2)
        txn.credit_available = round(float(card.credit_limit) - abs(running_balance), 2)
        
        if i < 5 or i >= len(transactions) - 5:
            print(f"  {txn.date} {txn.transaction_type:12} Amount:{txn.amount:>10.2f} Old:{old_balance:>10.2f} New:{txn.balance:>10.2f}")
        elif i == 5:
            print("  ...")
    
    db.session.flush()
    print("\nFlushed to database")
    
    # Check if it's there
    last_txn = transactions[-1]
    print(f"\nLast txn balance (in memory): {last_txn.balance}")
    
    # Requery
    db.session.expire(last_txn)
    print(f"Last txn balance (after expire, before requery): {last_txn.balance}")
