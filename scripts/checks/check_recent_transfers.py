"""Check recent transfer transactions in the database"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction
from datetime import datetime, timedelta

app = create_app()

with app.app_context():
    # Get all transactions from the last 7 days
    recent_date = datetime.now().date() - timedelta(days=7)
    
    recent_transfers = Transaction.query.filter(
        Transaction.transaction_date >= recent_date,
        Transaction.payment_type == 'Transfer'
    ).order_by(Transaction.created_at.desc()).all()
    
    print(f"\n{'='*80}")
    print(f"TRANSFER TRANSACTIONS FROM LAST 7 DAYS")
    print(f"{'='*80}\n")
    
    if not recent_transfers:
        print("❌ No transfer transactions found in the last 7 days")
        
        # Check if ANY transfers exist
        all_transfers = Transaction.query.filter_by(payment_type='Transfer').count()
        print(f"\nTotal transfers in database: {all_transfers}")
    else:
        print(f"Found {len(recent_transfers)} transfer transaction(s):\n")
        
        for txn in recent_transfers:
            print(f"ID: {txn.id}")
            print(f"  Account: {txn.account.name if txn.account else 'Unknown'}")
            print(f"  Amount: £{txn.amount:.2f}")
            print(f"  Date: {txn.transaction_date}")
            print(f"  Description: {txn.description}")
            print(f"  Linked Transaction ID: {txn.linked_transaction_id}")
            print(f"  Payday Period: {txn.payday_period}")
            print(f"  Created At: {txn.created_at}")
            print(f"  Is Paid: {txn.is_paid}")
            print()
    
    print(f"\n{'='*80}\n")
