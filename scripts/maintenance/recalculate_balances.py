"""
Recalculate all account balances from transactions
Balances should ONLY be driven by transactions, never manually edited
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models.accounts import Account
from models.transactions import Transaction
from datetime import datetime

def recalculate_all_balances():
    """
    Calculate account balances from the sum of all transactions.
    Formula: balance = sum(-amount) for all transactions
    Where: negative amounts = income/credits, positive amounts = expenses/debits
    """
    app = create_app()
    
    with app.app_context():
        print(f"\n{'='*80}")
        print(f"Recalculating Account Balances from Transactions")
        print(f"{'='*80}\n")
        
        all_accounts = Account.query.filter_by(is_active=True).all()
        
        for account in all_accounts:
            # Get all transactions for this account
            transactions = Transaction.query.filter_by(account_id=account.id).all()
            
            if not transactions:
                # No transactions, set balance to 0
                old_balance = float(account.balance) if account.balance else 0.0
                account.balance = 0.0
                print(f"{account.name:35} | Transactions: {len(transactions):>4} | Old: GBP {old_balance:>10.2f} | New: GBP {0.0:>10.2f}")
                continue
            
            # Calculate balance from transactions
            # Negative amounts = credits (income)
            # Positive amounts = debits (expenses)
            # Balance = sum of -amount
            balance = float(sum([-t.amount for t in transactions]))
            
            # Calculate totals for info
            income_total = float(sum([-t.amount for t in transactions if t.amount < 0]))
            expense_total = float(sum([t.amount for t in transactions if t.amount > 0]))
            
            old_balance = float(account.balance) if account.balance else 0.0
            account.balance = balance
            account.updated_at = datetime.now()
            
            print(f"{account.name:35} | Transactions: {len(transactions):>4} | Income: GBP {income_total:>10.2f} | Expenses: GBP {expense_total:>10.2f} | Balance: GBP {balance:>10.2f}")
            
            if abs(old_balance - balance) > 0.01:  # Show only if changed
                print(f"  -> Changed from GBP {old_balance:>10.2f}")
        
        # Commit all changes
        db.session.commit()
        
        print(f"\n{'='*80}")
        print(f"All account balances recalculated successfully!")
        print(f"{'='*80}\n")

if __name__ == '__main__':
    recalculate_all_balances()
