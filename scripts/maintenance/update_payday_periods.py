"""
Update payday_period for all transactions using PaydayService
This ensures all transactions have the correct payday period based on payday settings
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction
from services.payday_service import PaydayService


def update_all_payday_periods():
    """Update payday_period for all transactions"""
    app = create_app()
    
    with app.app_context():
        # Get all transactions
        transactions = Transaction.query.all()
        
        total = len(transactions)
        updated = 0
        skipped = 0
        
        print(f"\nFound {total} transactions to process")
        print("-" * 50)
        
        for txn in transactions:
            # Skip if no transaction_date
            if not txn.transaction_date:
                skipped += 1
                continue
            
            # Calculate correct payday_period
            old_period = txn.payday_period
            new_period = PaydayService.get_period_for_date(txn.transaction_date)
            
            # Update if different
            if old_period != new_period:
                txn.payday_period = new_period
                updated += 1
                
                if updated % 100 == 0:
                    print(f"Processed {updated} updates...")
        
        # Commit all changes
        print(f"\nCommitting changes...")
        db.session.commit()
        
        print("-" * 50)
        print(f"✓ Complete!")
        print(f"  Total transactions: {total}")
        print(f"  Updated: {updated}")
        print(f"  Skipped (no date): {skipped}")
        print(f"  Unchanged: {total - updated - skipped}")


if __name__ == '__main__':
    print("=" * 50)
    print("Update Payday Periods for All Transactions")
    print("=" * 50)
    
    response = input("\nThis will update payday_period for ALL transactions.\nContinue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        update_all_payday_periods()
    else:
        print("Cancelled.")
