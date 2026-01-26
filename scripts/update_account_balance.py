"""
Update account balance based on transaction history
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models.accounts import Account
from models.transactions import Transaction

def update_account_balance(account_name):
    """Calculate and update account balance from transactions"""
    app = create_app()
    
    with app.app_context():
        # Get the account
        account = Account.query.filter_by(name=account_name).first()
        
        if not account:
            print(f"❌ Account '{account_name}' not found")
            return
        
        # Get all transactions for this account
        transactions = Transaction.query.filter_by(account_id=account.id).all()
        
        if not transactions:
            print(f"⚠️  No transactions found for {account_name}")
            return
        
        # Calculate balance
        # In the CSV: negative amounts are income (credits), positive are expenses (debits)
        # So balance = sum of all negative amounts (income) minus sum of positive amounts (expenses)
        # Which is the same as: -sum(all amounts)
        balance = sum([-t.amount for t in transactions])
        
        print(f"\n{'='*80}")
        print(f"📊 Account Balance Update")
        print(f"{'='*80}")
        print(f"Account: {account.name}")
        print(f"Transaction count: {len(transactions)}")
        print(f"Current balance in database: £{account.balance:,.2f}" if account.balance else "Current balance: None")
        print(f"Calculated balance from transactions: £{balance:,.2f}")
        print(f"{'='*80}\n")
        
        # Update the account balance
        account.balance = balance
        db.session.commit()
        
        print(f"✅ Account balance updated to £{balance:,.2f}")
        
        # Show some transaction statistics
        income_transactions = [t for t in transactions if t.amount < 0]
        expense_transactions = [t for t in transactions if t.amount > 0]
        
        total_income = sum([-t.amount for t in income_transactions])
        total_expenses = sum([t.amount for t in expense_transactions])
        
        print(f"\n📈 Transaction Summary:")
        print(f"   Income transactions: {len(income_transactions)} (£{total_income:,.2f})")
        print(f"   Expense transactions: {len(expense_transactions)} (£{total_expenses:,.2f})")
        print(f"   Net balance: £{balance:,.2f}")

if __name__ == '__main__':
    update_account_balance('Nationwide Current Account')
