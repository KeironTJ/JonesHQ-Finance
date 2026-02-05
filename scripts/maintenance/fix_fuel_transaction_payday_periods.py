"""
Fix payday_period for all fuel transactions
Recalculates payday_period using the correct get_period_for_date() method
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.transactions import Transaction
from models.fuel import FuelRecord
from models.categories import Category
from services.payday_service import PaydayService
from extensions import db

app = create_app()

with app.app_context():
    print("=" * 80)
    print("Fixing payday_period for all fuel transactions")
    print("=" * 80)
    
    # Get fuel category
    fuel_category = Category.query.filter_by(name='Transportation - Fuel').first()
    
    if not fuel_category:
        print("❌ No 'Transportation - Fuel' category found")
        sys.exit(1)
    
    # Get all fuel records with linked transactions
    fuel_records = FuelRecord.query.filter(FuelRecord.linked_transaction_id != None).all()
    
    print(f"\nFound {len(fuel_records)} fuel records with linked transactions")
    
    if len(fuel_records) == 0:
        print("Nothing to update!")
        sys.exit(0)
    
    # Also get fuel transactions by category
    fuel_txns = Transaction.query.filter_by(category_id=fuel_category.id).all()
    print(f"Found {len(fuel_txns)} transactions in 'Transportation - Fuel' category")
    
    # Collect all unique transaction IDs to update
    txn_ids = set()
    for fuel_record in fuel_records:
        txn_ids.add(fuel_record.linked_transaction_id)
    for txn in fuel_txns:
        txn_ids.add(txn.id)
    
    print(f"\nTotal unique fuel transactions to update: {len(txn_ids)}")
    
    # Update each transaction
    updated_count = 0
    changed_count = 0
    
    print("\nUpdating transactions...")
    for txn_id in txn_ids:
        txn = Transaction.query.get(txn_id)
        if not txn or not txn.transaction_date:
            continue
        
        # Calculate correct payday period
        old_period = txn.payday_period
        new_period = PaydayService.get_period_for_date(txn.transaction_date)
        
        # Also update other computed fields for consistency
        txn.payday_period = new_period
        txn.year_month = txn.transaction_date.strftime('%Y-%m')
        txn.week_year = f"{txn.transaction_date.isocalendar()[1]:02d}-{txn.transaction_date.year}"
        txn.day_name = txn.transaction_date.strftime('%a')
        
        updated_count += 1
        
        if old_period != new_period:
            changed_count += 1
            print(f"  {txn.transaction_date} | {txn.description[:40]:40} | {old_period or 'None':7} -> {new_period}")
    
    # Commit all changes
    db.session.commit()
    
    print("\n" + "=" * 80)
    print(f"✅ Successfully updated {updated_count} fuel transactions")
    print(f"   {changed_count} transactions had their payday_period changed")
    print(f"   {updated_count - changed_count} transactions were already correct")
    print("=" * 80)
    
    # Show summary by period
    print("\nFuel transactions by payday period:")
    from sqlalchemy import func
    period_counts = db.session.query(
        Transaction.payday_period,
        func.count(Transaction.id)
    ).filter(
        Transaction.id.in_(list(txn_ids))
    ).group_by(
        Transaction.payday_period
    ).order_by(
        Transaction.payday_period.desc()
    ).limit(12).all()
    
    for period, count in period_counts:
        print(f"  {period}: {count} transactions")
