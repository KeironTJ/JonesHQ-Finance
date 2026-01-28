"""
Import credit card transactions from CCDATA_ACTUAL.csv
"""
import sys
import os
import csv
from datetime import datetime
from decimal import Decimal

# Add parent directory to path to import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import CreditCard, CreditCardTransaction, Category


def parse_date(date_str):
    """Parse date from DD/MM/YYYY format"""
    return datetime.strptime(date_str, '%d/%m/%Y').date()


def parse_amount(amount_str):
    """Parse amount - CSV has negative for purchases/interest, positive for payments"""
    return Decimal(str(amount_str))


def get_or_create_category(head_budget, sub_budget):
    """Find or create category"""
    category = Category.query.filter_by(
        head_budget=head_budget,
        sub_budget=sub_budget
    ).first()
    
    if not category:
        # Create category name from head + sub
        name = f"{head_budget} - {sub_budget}"
        category = Category(
            name=name,
            head_budget=head_budget,
            sub_budget=sub_budget,
            category_type='Expense'  # Default
        )
        db.session.add(category)
        db.session.flush()
        print(f"  Created new category: {head_budget} > {sub_budget}")
    
    return category


def import_credit_card_transactions(csv_file_path):
    """Import credit card transactions from CSV"""
    app = create_app()
    
    with app.app_context():
        print("Starting credit card transaction import...")
        print("-" * 70)
        
        # Get all credit cards for lookup
        cards = {card.card_name: card for card in CreditCard.query.all()}
        print(f"Found {len(cards)} credit cards in database: {', '.join(cards.keys())}")
        print("-" * 70)
        
        imported_count = 0
        skipped_count = 0
        error_count = 0
        
        with open(csv_file_path, 'r', encoding='utf-8-sig') as f:  # utf-8-sig handles BOM
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, start=2):  # start=2 because row 1 is header
                try:
                    card_name = row['Card'].strip()
                    
                    # Skip if card not found
                    if card_name not in cards:
                        print(f"⚠️  Row {row_num}: Card '{card_name}' not found in database - SKIPPED")
                        skipped_count += 1
                        continue
                    
                    card = cards[card_name]
                    
                    # Parse transaction data
                    txn_date = parse_date(row['Date'])
                    txn_type = row['Transaction Type'].strip()
                    amount = parse_amount(row['Amount'])
                    head_budget = row['Head Budget'].strip()
                    sub_budget = row['Sub Budget'].strip()
                    description = row['Item'].strip()
                    
                    # Get or create category
                    category = get_or_create_category(head_budget, sub_budget)
                    
                    # Check for duplicate transaction
                    existing = CreditCardTransaction.query.filter_by(
                        credit_card_id=card.id,
                        date=txn_date,
                        transaction_type=txn_type,
                        amount=amount,
                        item=description
                    ).first()
                    
                    if existing:
                        print(f"⏭️  Row {row_num}: {card_name} - {txn_date} - {description} (£{amount}) - DUPLICATE, SKIPPED")
                        skipped_count += 1
                        continue
                    
                    # Create transaction
                    transaction = CreditCardTransaction(
                        credit_card_id=card.id,
                        date=txn_date,
                        transaction_type=txn_type,
                        amount=amount,
                        item=description,  # Use 'item' field for description
                        category_id=category.id
                    )
                    
                    db.session.add(transaction)
                    imported_count += 1
                    
                    if imported_count % 50 == 0:
                        print(f"✓ Imported {imported_count} transactions...")
                    
                except Exception as e:
                    print(f"❌ Row {row_num}: ERROR - {str(e)}")
                    print(f"   Data: {row}")
                    error_count += 1
                    continue
        
        # Commit all transactions
        print("\nCommitting transactions to database...")
        db.session.commit()
        print("✓ Committed!")
        
        print("\n" + "=" * 70)
        print("IMPORT SUMMARY")
        print("=" * 70)
        print(f"✓ Successfully imported: {imported_count} transactions")
        print(f"⏭️  Skipped (duplicates/missing cards): {skipped_count}")
        print(f"❌ Errors: {error_count}")
        print(f"📊 Total rows processed: {imported_count + skipped_count + error_count}")
        
        # Recalculate balances for all cards
        print("\n" + "-" * 70)
        print("Recalculating card balances...")
        print("-" * 70)
        
        for card_name, card in cards.items():
            print(f"\nRecalculating {card_name}...")
            CreditCardTransaction.recalculate_card_balance(card.id)
            db.session.commit()
            
            # Show current balance
            updated_card = CreditCard.query.get(card.id)
            print(f"  Current balance: £{updated_card.current_balance:,.2f}")
        
        # Auto-regenerate future transactions
        print("\n" + "=" * 70)
        print("AUTO-REGENERATING FUTURE TRANSACTIONS")
        print("=" * 70)
        print("Deleting non-fixed future transactions and regenerating...")
        
        from services.credit_card_service import CreditCardService
        from datetime import date
        from dateutil.relativedelta import relativedelta
        
        # Regenerate from today through 2035
        today = date.today()
        end_date = date(2035, 12, 31)
        
        results = CreditCardService.regenerate_all_future_transactions(
            start_date=today,
            end_date=end_date,
            payment_offset_days=14
        )
        
        print(f"\n✅ Regeneration complete:")
        print(f"   Cards processed: {results['cards_processed']}")
        print(f"   Deleted non-fixed transactions: {results['total_deleted']}")
        print(f"   Created statements: {results['total_statements']}")
        print(f"   Created payments: {results['total_payments']}")
        
        print("\n✅ Import complete!")


if __name__ == '__main__':
    # Path to CSV file
    csv_path = os.path.join(
        os.path.dirname(__file__),
        'data',
        'CCDATA_ACTUAL.csv'
    )
    
    if not os.path.exists(csv_path):
        print(f"❌ ERROR: CSV file not found at {csv_path}")
        sys.exit(1)
    
    print(f"CSV file: {csv_path}")
    print()
    
    # Confirm before proceeding
    response = input("This will import credit card transactions. Continue? (yes/no): ")
    if response.lower() != 'yes':
        print("Import cancelled.")
        sys.exit(0)
    
    import_credit_card_transactions(csv_path)
