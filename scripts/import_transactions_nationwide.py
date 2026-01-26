"""
Import transactions for Nationwide Joint Account - TEMPLATE
⚠️ WARNING: This is a template with placeholder values
Copy this file to import_transactions_nationwide_ACTUAL.py and fill in your real data
The _ACTUAL.py file is gitignored for security
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from datetime import datetime
from app import create_app, db
from models.transactions import Transaction
from models.categories import Category
from models.accounts import Account
from models.vendors import Vendor

def parse_amount(amount_str):
    """Parse amount string like '£123.45' or '-£123.45' to float"""
    if not amount_str or amount_str.strip() == '£-':
        return 0.0
    
    # Remove £, commas, and spaces
    cleaned = amount_str.replace('£', '').replace(',', '').replace(' ', '').strip()
    
    # Handle empty or dash
    if cleaned == '-' or cleaned == '':
        return 0.0
    
    # Convert to float (negative if starts with -)
    return float(cleaned)

def parse_date(date_str):
    """Parse date string DD/MM/YYYY to datetime"""
    return datetime.strptime(date_str, '%d/%m/%Y')

def get_or_create_category(head_budget, sub_budget):
    """Get or create category based on head and sub budget"""
    # Try to find existing category
    category = Category.query.filter_by(
        category_name=sub_budget,
        head_budget=head_budget
    ).first()
    
    if not category:
        # Create new category if not found
        category = Category(
            category_name=sub_budget,
            head_budget=head_budget,
            category_type='Expense'  # Default to expense
        )
        db.session.add(category)
        db.session.flush()
    
    return category

def get_or_create_vendor(item_name):
    """Get or create vendor based on item name"""
    if not item_name or item_name.strip() == '':
        item_name = 'Unknown'
    
    # Try to find existing vendor (case-insensitive)
    vendor = Vendor.query.filter(
        db.func.lower(Vendor.vendor_name) == item_name.lower()
    ).first()
    
    if not vendor:
        # Create new vendor
        vendor = Vendor(
            vendor_name=item_name,
            vendor_type='Other'
        )
        db.session.add(vendor)
        db.session.flush()
    
    return vendor

# Transaction data - TEMPLATE WITH SAMPLE DATA
# ⚠️ Replace with your actual transaction data in the _ACTUAL.py file
TRANSACTIONS = [
    # Format: Date, Year Month, Week Year, Day, Head Budget, Sub Budget, Item, Assign, Payment Type, Budget, Running Budget, Paid?
    ('22/08/2024', '2024-08', '34-2024', 'Thu', 'General', 'General Spending', 'Transfer IN', 'Keiron', 'Transfer', '-£5.00', '£5.00', True),
    ('22/08/2024', '2024-08', '34-2024', 'Thu', 'Savings', 'Christmas', '2024', '', 'Transfer', '£1.00', '£4.00', True),
    # Add your actual transactions here...
]

def import_transactions():
    """Import all transactions"""
    app = create_app()
    
    with app.app_context():
        # Get the Nationwide Joint account
        account = Account.query.filter_by(account_name='Nationwide Joint').first()
        
        if not account:
            print("❌ Error: Nationwide Joint account not found!")
            print("Please run import_accounts.py first")
            return
        
        print(f"📊 Importing transactions for {account.account_name}...")
        print(f"Account ID: {account.account_id}")
        print(f"Account Type: {account.account_type}")
        print(f"Current Balance: £{account.current_balance:,.2f}")
        print(f"\n{'='*80}\n")
        
        imported_count = 0
        skipped_count = 0
        error_count = 0
        
        for trans_data in TRANSACTIONS:
            try:
                date_str, year_month, week_year, day, head_budget, sub_budget, item, assign, payment_type, budget_str, running_budget_str, paid = trans_data
                
                # Parse date and amount
                trans_date = parse_date(date_str)
                amount = parse_amount(budget_str)
                
                # Skip if amount is 0
                if amount == 0:
                    skipped_count += 1
                    continue
                
                # Get or create category
                category = get_or_create_category(head_budget, sub_budget)
                
                # Get or create vendor
                vendor = get_or_create_vendor(item)
                
                # Determine transaction type based on amount
                if amount < 0:
                    trans_type = 'Income'
                    amount = abs(amount)  # Store as positive
                else:
                    trans_type = 'Expense'
                
                # Check if transaction already exists (to avoid duplicates)
                existing = Transaction.query.filter_by(
                    account_id=account.account_id,
                    transaction_date=trans_date,
                    amount=amount,
                    vendor_id=vendor.vendor_id
                ).first()
                
                if existing:
                    skipped_count += 1
                    continue
                
                # Create transaction
                transaction = Transaction(
                    account_id=account.account_id,
                    transaction_date=trans_date,
                    amount=amount,
                    category_id=category.category_id,
                    vendor_id=vendor.vendor_id,
                    description=f"{item} - {assign}" if assign else item,
                    transaction_type=trans_type,
                    payment_method=payment_type,
                    is_recurring=False,
                    notes=f"Week: {week_year}, Day: {day}"
                )
                
                db.session.add(transaction)
                imported_count += 1
                
                # Commit in batches of 100
                if imported_count % 100 == 0:
                    db.session.commit()
                    print(f"✅ Imported {imported_count} transactions...")
                
            except Exception as e:
                error_count += 1
                print(f"❌ Error importing transaction: {e}")
                print(f"   Data: {trans_data}")
                continue
        
        # Final commit
        db.session.commit()
        
        print(f"\n{'='*80}\n")
        print(f"✅ Import Complete!")
        print(f"📊 Imported: {imported_count} transactions")
        print(f"⏭️  Skipped: {skipped_count} transactions (duplicates or zero amounts)")
        print(f"❌ Errors: {error_count} transactions")
        print(f"\n{'='*80}")

if __name__ == '__main__':
    import_transactions()
