"""
Update savings account balances to match actual bank records
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models.accounts import Account

def update_savings_balances():
    """Update savings account balances to correct values"""
    app = create_app()
    
    with app.app_context():
        # Define correct balances
        correct_balances = {
            'Nationwide - Motor': 0.00,
            'Nationwide - Mr Dales': 31.00,
            'Nationwide - Christmas': 250.00,
            'Nationwide - Home': 0.00,
            'Nationwide - Clothing': 190.03,
            'Nationwide - Holiday': 1729.15
        }
        
        print("\n" + "="*80)
        print("Updating Savings Account Balances")
        print("="*80)
        
        for account_name, correct_balance in correct_balances.items():
            account = Account.query.filter_by(name=account_name).first()
            
            if account:
                old_balance = account.balance or 0.00
                account.balance = correct_balance
                
                print(f"{account_name:30} | Old: GBP {old_balance:>10.2f} | New: GBP {correct_balance:>10.2f}")
            else:
                print(f"WARNING: Account '{account_name}' not found")
        
        db.session.commit()
        
        print("="*80)
        print("All savings balances updated successfully!")
        print("="*80 + "\n")

if __name__ == '__main__':
    update_savings_balances()
