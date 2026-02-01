"""Check all transactions created today"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction
from datetime import datetime, date

app = create_app()

with app.app_context():
    # Get today's date
    today = date.today()
    
    # Get all transactions created today (by created_at timestamp)
    todays_transactions = Transaction.query.filter(
        db.func.date(Transaction.created_at) == today
    ).order_by(Transaction.created_at.desc()).all()
    
    print(f"\n{'='*80}")
    print(f"TRANSACTIONS CREATED TODAY ({today})")
    print(f"{'='*80}\n")
    
    if not todays_transactions:
        print("❌ No transactions created today")
    else:
        print(f"Found {len(todays_transactions)} transaction(s) created today:\n")
        
        for txn in todays_transactions:
            print(f"ID: {txn.id}")
            print(f"  Account: {txn.account.name if txn.account else 'Unknown'}")
            print(f"  Amount: £{txn.amount:.2f}")
            print(f"  Transaction Date: {txn.transaction_date}")
            print(f"  Description: {txn.description}")
            print(f"  Payment Type: {txn.payment_type}")
            print(f"  Payday Period: {txn.payday_period}")
            print(f"  Linked Transaction ID: {txn.linked_transaction_id}")
            print(f"  Created At: {txn.created_at}")
            print(f"  Category: {txn.category.name if txn.category else 'None'}")
            print(f"  Vendor: {txn.vendor.name if txn.vendor else 'None'}")
            print()
    
    print(f"\n{'='*80}\n")
