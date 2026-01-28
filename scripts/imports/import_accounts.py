"""
Import bank accounts (Current and Savings)
Run this script to populate the accounts table with bank account data
"""
import sys
import os

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Account

# Account data
ACCOUNTS = [
    # Nationwide Current Account
    {
        'name': 'Nationwide Current Account',
        'account_type': 'Joint',
        'balance': 0.00,  # Update with actual balance
        'is_active': True
    },
    
    # Nationwide Savings Accounts
    {
        'name': 'Nationwide - Clothing',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Nationwide - Home',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Nationwide - Holiday',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Nationwide - Motor',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Nationwide - Christmas',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Nationwide - Mr Dales',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    
    # Halifax Current Account
    {
        'name': 'Halifax Current Account',
        'account_type': 'Personal',
        'balance': 0.00,
        'is_active': True
    },
    
    # Halifax Savings Accounts
    {
        'name': 'Halifax - Michael',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Halifax - Emily',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Halifax - Ivy',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Halifax - Brian',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Halifax - General',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
    {
        'name': 'Halifax - Emma',
        'account_type': 'Savings',
        'balance': 0.00,
        'is_active': True
    },
]


def import_accounts():
    """Import all accounts into database"""
    app = create_app()
    
    with app.app_context():
        print("Starting account import...")
        print(f"Total accounts to import: {len(ACCOUNTS)}")
        print("-" * 50)
        
        imported_count = 0
        skipped_count = 0
        
        for account_data in ACCOUNTS:
            # Check if account already exists
            existing = Account.query.filter_by(name=account_data['name']).first()
            
            if existing:
                print(f"⏭️  Skipped: {account_data['name']} (already exists)")
                skipped_count += 1
                continue
            
            # Create new account
            account = Account(
                name=account_data['name'],
                account_type=account_data['account_type'],
                balance=account_data['balance'],
                is_active=account_data['is_active']
            )
            
            db.session.add(account)
            imported_count += 1
            
            # Show account type for clarity
            type_emoji = "🏦" if account_data['account_type'] == 'Joint' else "👤" if account_data['account_type'] == 'Personal' else "💰"
            print(f"{type_emoji} Added: {account_data['name']} ({account_data['account_type']})")
        
        # Commit all accounts
        db.session.commit()
        
        print("-" * 50)
        print(f"✅ Import complete!")
        print(f"   Imported: {imported_count} accounts")
        print(f"   Skipped: {skipped_count} accounts")
        print(f"   Total in database: {Account.query.count()} accounts")
        
        # Show summary by type
        print("\n📊 Summary by type:")
        for account_type in ['Joint', 'Personal', 'Savings']:
            count = Account.query.filter_by(account_type=account_type, is_active=True).count()
            if count > 0:
                print(f"   {account_type}: {count}")


if __name__ == '__main__':
    import_accounts()
