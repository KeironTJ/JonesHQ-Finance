"""Fix all account balances by recalculating from transactions"""
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
    print(f"\n{'='*80}")
    print(f"RECALCULATING ALL ACCOUNT BALANCES")
    print(f"{'='*80}\n")
    
    accounts = Account.query.all()
    
    for account in accounts:
        old_balance = float(account.balance) if account.balance else 0.0
        
        # Recalculate using the fixed method
        Transaction.recalculate_account_balance(account.id)
        
        # Get updated balance (don't refresh, it's already updated in memory)
        new_balance = float(account.balance) if account.balance else 0.0
        
        print(f"{account.name}:")
        print(f"  Old Balance: £{old_balance:,.2f}")
        print(f"  New Balance: £{new_balance:,.2f}")
        print(f"  Change: £{new_balance - old_balance:,.2f}")
        print()
    
    # Commit all changes
    db.session.commit()
    print(f"✓ All account balances recalculated and saved")
    print(f"\n{'='*80}\n")
