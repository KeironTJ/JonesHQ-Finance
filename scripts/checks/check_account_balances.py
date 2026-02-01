"""Check account balances and recent transactions"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.accounts import Account
from models.transactions import Transaction
from datetime import datetime

app = create_app()

with app.app_context():
    # Get the two accounts involved in the transfer
    clothing_account = Account.query.filter_by(name='Nationwide - Clothing').first()
    current_account = Account.query.filter_by(name='Nationwide Current Account').first()
    
    print(f"\n{'='*80}")
    print(f"ACCOUNT BALANCES")
    print(f"{'='*80}\n")
    
    if clothing_account:
        print(f"Nationwide - Clothing:")
        print(f"  Current Balance: £{clothing_account.balance:.2f}")
        
        # Get recent transactions for this account
        recent = Transaction.query.filter_by(account_id=clothing_account.id).order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(5).all()
        print(f"  Recent transactions:")
        for txn in recent:
            print(f"    {txn.transaction_date} | £{txn.amount:7.2f} | {txn.description[:40]}")
    
    print()
    
    if current_account:
        print(f"Nationwide Current Account:")
        print(f"  Current Balance: £{current_account.balance:.2f}")
        
        # Get recent transactions for this account
        recent = Transaction.query.filter_by(account_id=current_account.id).order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc()).limit(5).all()
        print(f"  Recent transactions:")
        for txn in recent:
            print(f"    {txn.transaction_date} | £{txn.amount:7.2f} | {txn.description[:40]}")
    
    print(f"\n{'='*80}\n")
    
    # Now manually calculate what the balances SHOULD be
    print(f"MANUAL BALANCE CALCULATION\n")
    
    if clothing_account:
        all_txns = Transaction.query.filter_by(account_id=clothing_account.id).order_by(Transaction.transaction_date, Transaction.created_at).all()
        balance = 0
        for txn in all_txns:
            balance += txn.amount
        print(f"Nationwide - Clothing:")
        print(f"  DB Balance: £{clothing_account.balance:.2f}")
        print(f"  Calculated Balance: £{balance:.2f}")
        print(f"  Difference: £{clothing_account.balance - balance:.2f}")
    
    print()
    
    if current_account:
        all_txns = Transaction.query.filter_by(account_id=current_account.id).order_by(Transaction.transaction_date, Transaction.created_at).all()
        balance = 0
        for txn in all_txns:
            balance += txn.amount
        print(f"Nationwide Current Account:")
        print(f"  DB Balance: £{current_account.balance:.2f}")
        print(f"  Calculated Balance: £{balance:.2f}")
        print(f"  Difference: £{current_account.balance - balance:.2f}")
    
    print(f"\n{'='*80}\n")
