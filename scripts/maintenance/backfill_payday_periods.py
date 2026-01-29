"""
Backfill payday_period for all existing transactions
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.transactions import Transaction
from services.payday_service import PaydayService
from extensions import db

app = create_app()

with app.app_context():
    print("Backfilling payday_period for all transactions...")
    
    # Get all transactions that don't have a payday_period set
    transactions = Transaction.query.filter(
        (Transaction.payday_period == None) | (Transaction.payday_period == '')
    ).all()
    
    print(f"Found {len(transactions)} transactions to update")
    
    updated_count = 0
    batch_size = 100
    
    for i, txn in enumerate(transactions):
        # Calculate payday period based on transaction_date
        if txn.transaction_date:
            payday_period = PaydayService.get_period_for_date(txn.transaction_date)
            txn.payday_period = payday_period
            updated_count += 1
            
            # Commit in batches
            if (i + 1) % batch_size == 0:
                db.session.commit()
                print(f"Updated {i + 1}/{len(transactions)} transactions...")
    
    # Final commit
    db.session.commit()
    
    print(f"\n✅ Successfully updated {updated_count} transactions with payday_period")
    
    # Verify results
    print("\nVerification:")
    total = Transaction.query.count()
    with_period = Transaction.query.filter(Transaction.payday_period != None).count()
    print(f"Total transactions: {total}")
    print(f"Transactions with payday_period: {with_period}")
    
    # Show sample
    print("\nSample transactions:")
    samples = Transaction.query.filter(Transaction.payday_period != None).limit(10).all()
    for txn in samples:
        print(f"  {txn.transaction_date} -> {txn.payday_period}: {txn.description}")
