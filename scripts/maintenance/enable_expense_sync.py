"""
Script to enable expense sync service and configure required settings.
Run this once to activate the automatic expense transaction creation.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.settings import Settings
from models.accounts import Account
from models.categories import Category

def enable_expense_sync():
    """Enable expense sync service and create required settings"""
    app = create_app()
    
    with app.app_context():
        print("Enabling Expense Sync Service...")
        
        # Enable auto sync
        Settings.set_value(
            'expenses.auto_sync',
            'True',
            description='Enable automatic expense to transaction syncing',
            setting_type='boolean'
        )
        print("✓ Set expenses.auto_sync = True")
        
        # Set default payment account (for direct bank expenses)
        accounts = Account.query.order_by(Account.name).all()
        if accounts:
            default_account = accounts[0]
            Settings.set_value(
                'expenses.payment_account_id',
                str(default_account.id),
                description='Default account for direct expense payments',
                setting_type='int'
            )
            print(f"✓ Set expenses.payment_account_id = {default_account.id} ({default_account.name})")
        else:
            print("⚠ No accounts found - you'll need to set expenses.payment_account_id manually")
        
        # Set default reimbursement account (where employer pays back)
        if accounts:
            default_reimburse = accounts[0]  # Usually same as payment account
            Settings.set_value(
                'expenses.reimburse_account_id',
                str(default_reimburse.id),
                description='Account where expense reimbursements are received',
                setting_type='int'
            )
            print(f"✓ Set expenses.reimburse_account_id = {default_reimburse.id} ({default_reimburse.name})")
        
        # Create required categories if they don't exist
        
        # 1. Income > Expense Reimbursement
        reimburse_cat = Category.query.filter_by(
            head_budget='Income',
            sub_budget='Expense Reimbursement'
        ).first()
        
        if not reimburse_cat:
            reimburse_cat = Category(
                name='Expense Reimbursement',
                head_budget='Income',
                sub_budget='Expense Reimbursement',
                category_type='income'
            )
            db.session.add(reimburse_cat)
            print("✓ Created category: Income > Expense Reimbursement")
        else:
            print("✓ Category already exists: Income > Expense Reimbursement")
        
        # 2. Income > Expense
        expense_cat = Category.query.filter_by(
            head_budget='Income',
            sub_budget='Expense'
        ).first()
        
        if not expense_cat:
            expense_cat = Category(
                name='Expense',
                head_budget='Income',
                sub_budget='Expense',
                category_type='expense'
            )
            db.session.add(expense_cat)
            print("✓ Created category: Income > Expense")
        else:
            print("✓ Category already exists: Income > Expense")
        
        db.session.commit()
        
        print("\n" + "="*60)
        print("Expense Sync Service Enabled Successfully!")
        print("="*60)
        print("\nNext steps:")
        print("1. Verify account settings in Settings page")
        print("2. Add/edit expenses - transactions will be created automatically")
        print("3. Mark expenses as 'Submitted' when ready")
        print("4. Use 'Generate Reimbursements' button to create monthly reimbursements")
        print("5. Use 'Generate CC Payments' button to create auto payments")
        print("\nConfiguration:")
        print(f"  - Payment Account: {default_account.name if accounts else 'NOT SET'}")
        print(f"  - Reimbursement Account: {default_reimburse.name if accounts else 'NOT SET'}")
        print(f"  - Auto Sync: Enabled")

if __name__ == '__main__':
    enable_expense_sync()
