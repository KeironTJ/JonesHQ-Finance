"""Debug account balance calculation"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.accounts import Account
from models.transactions import Transaction

app = create_app()

with app.app_context():
    # Check Nationwide - Clothing account
    account = Account.query.filter_by(name='Nationwide - Clothing').first()
    
    if account:
        print(f"\nNationwide - Clothing (ID: {account.id})")
        print(f"Current DB Balance: £{account.balance:.2f}\n")
        
        transactions = Transaction.query.filter_by(account_id=account.id).all()
        print(f"Total transactions: {len(transactions)}\n")
        
        # Show first 10 transactions
        print("First 10 transactions:")
        for txn in transactions[:10]:
            print(f"  {txn.transaction_date} | £{txn.amount:8.2f} | {txn.description[:40]}")
        
        # Calculate balance manually
        balance_old_way = float(sum([-t.amount for t in transactions]))
        balance_new_way = float(sum([t.amount for t in transactions]))
        
        print(f"\nOld calculation (negating): £{balance_old_way:.2f}")
        print(f"New calculation (direct sum): £{balance_new_way:.2f}")
        print(f"Current DB Balance: £{account.balance:.2f}")
