"""
Import transactions from CSV file for Nationwide Joint Account
This script reads from a CSV file and imports transactions
"""

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import csv
from datetime import datetime
from app import create_app, db
from models.transactions import Transaction
from models.categories import Category
from models.accounts import Account
from models.vendors import Vendor

def parse_amount(amount_str):
    """Parse amount string like '£123.45' or '-£123.45' to float"""
    if not amount_str or amount_str.strip() in ['£-', '-', '']:
        return 0.0
    
    # Remove £, commas, and spaces
    cleaned = amount_str.replace('£', '').replace(',', '').replace(' ', '').strip()
    
    if cleaned == '' or cleaned == '-':
        return 0.0
    
    return float(cleaned)

def parse_date(date_str):
    """Parse date string DD/MM/YYYY to datetime"""
    return datetime.strptime(date_str, '%d/%m/%Y')

def get_or_create_category(head_budget, sub_budget):
    """Get or create category based on head and sub budget"""
    category = Category.query.filter_by(
        sub_budget=sub_budget,
        head_budget=head_budget
    ).first()
    
    if not category:
        category = Category(
            name=sub_budget,  # Use sub_budget as the category name
            sub_budget=sub_budget,
            head_budget=head_budget,
            category_type='Expense'
        )
        db.session.add(category)
        db.session.flush()
    
    return category

def get_or_create_vendor(item_name):
    """Get or create vendor based on item name"""
    if not item_name or item_name.strip() == '':
        item_name = 'Unknown'
    
    vendor = Vendor.query.filter(
        db.func.lower(Vendor.name) == item_name.lower()
    ).first()
    
    if not vendor:
        vendor = Vendor(
            name=item_name,
            vendor_type='Other'
        )
        db.session.add(vendor)
        db.session.flush()
    
    return vendor

def import_from_csv(csv_file_path):
    """Import transactions from CSV file"""
    app = create_app()
    
    with app.app_context():
        # Get the Nationwide Joint account
        account = Account.query.filter_by(name='Nationwide Current Account').first()
        
        if not account:
            print("❌ Error: Nationwide Joint account not found!")
            return
        
        print(f"📊 Importing transactions from CSV...")
        print(f"📁 File: {csv_file_path}")
        print(f"💳 Account: {account.name}")
        print(f"\n{'='*80}\n")
        
        imported_count = 0
        skipped_count = 0
        error_count = 0
        
        # Try different encodings for Windows CSV files
        encodings = ['cp1252', 'latin-1', 'utf-8-sig', 'utf-8']
        csvfile = None
        
        for encoding in encodings:
            try:
                csvfile = open(csv_file_path, 'r', encoding=encoding)
                # Test reading the first line
                csvfile.readline()
                csvfile.seek(0)
                break
            except UnicodeDecodeError:
                if csvfile:
                    csvfile.close()
                continue
        
        if csvfile is None:
            print("❌ Could not read CSV file with any encoding")
            return
        
        with csvfile:
            # Skip the header row
            reader = csv.reader(csvfile)
            header = next(reader)
            
            for row in reader:
                try:
                    if len(row) < 12:
                        continue
                    
                    date_str, year_month, week_year, day, head_budget, sub_budget, item, assign, payment_type, budget_str, running_budget_str, paid_str = row[:12]
                    
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
                    
                    # Check for duplicates
                    existing = Transaction.query.filter_by(
                        account_id=account.id,
                        transaction_date=trans_date,
                        amount=amount,
                        vendor_id=vendor.id
                    ).first()
                    
                    if existing:
                        skipped_count += 1
                        continue
                    
                    # Create transaction
                    transaction = Transaction(
                        account_id=account.id,
                        transaction_date=trans_date,
                        amount=amount,
                        category_id=category.id,
                        vendor_id=vendor.id,
                        description=f"{item} - {assign}" if assign else item,
                        item=item,
                        assigned_to=assign,
                        payment_type=payment_type,
                        year_month=year_month,
                        week_year=week_year,
                        day_name=day,
                        is_paid=True
                    )
                    
                    db.session.add(transaction)
                    imported_count += 1
                    
                    # Commit in batches
                    if imported_count % 100 == 0:
                        db.session.commit()
                        print(f"✅ Imported {imported_count} transactions...")
                
                except Exception as e:
                    error_count += 1
                    print(f"❌ Error: {e}")
                    print(f"   Row: {row[:3]}...")
                    continue
        
        # Final commit
        db.session.commit()
        
        print(f"\n{'='*80}\n")
        print(f"✅ Import Complete!")
        print(f"📊 Imported: {imported_count} transactions")
        print(f"⏭️  Skipped: {skipped_count} (duplicates/zero amounts)")
        print(f"❌ Errors: {error_count}")
        print(f"\n{'='*80}")

if __name__ == '__main__':
    # Path to your CSV file
    csv_path = Path(__file__).parent / 'data' / 'transaction_data_csv_ACTUAL.csv'
    
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        print("\nPlease create the CSV file with your transaction data:")
        print(f"  1. Create folder: {csv_path.parent}")
        print(f"  2. Save your transactions as: {csv_path.name}")
        print("  3. Run this script again")
    else:
        import_from_csv(csv_path)
