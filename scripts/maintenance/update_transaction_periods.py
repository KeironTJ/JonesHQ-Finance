"""
Update year_month and payday_period for all transactions
Run this to ensure all transactions have these computed fields populated
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from extensions import db
from models.transactions import Transaction
from services.payday_service import PaydayService
from datetime import date


def update_transaction_periods():
    """Update year_month and payday_period for all transactions"""
    app = create_app()
    
    with app.app_context():
        # Get all transactions
        transactions = Transaction.query.all()
        total = len(transactions)
        updated = 0
        
        print(f"Processing {total} transactions...")
        
        for i, transaction in enumerate(transactions, 1):
            if i % 100 == 0:
                print(f"Progress: {i}/{total}")
            
            trans_date = transaction.transaction_date
            
            # Calculate year_month
            year_month = f"{trans_date.year:04d}-{trans_date.month:02d}"
            
            # Calculate payday_period
            payday_period = None
            
            # Check current month
            start_date, end_date, period_label = PaydayService.get_payday_period(trans_date.year, trans_date.month)
            if start_date <= trans_date <= end_date:
                payday_period = period_label
            else:
                # Check previous month
                prev_month = trans_date.month - 1
                prev_year = trans_date.year
                if prev_month < 1:
                    prev_month = 12
                    prev_year -= 1
                start_date, end_date, period_label = PaydayService.get_payday_period(prev_year, prev_month)
                if start_date <= trans_date <= end_date:
                    payday_period = period_label
            
            # Update if different
            if transaction.year_month != year_month or transaction.payday_period != payday_period:
                transaction.year_month = year_month
                transaction.payday_period = payday_period
                updated += 1
        
        # Commit all changes
        db.session.commit()
        
        print(f"\nComplete!")
        print(f"Total transactions: {total}")
        print(f"Updated: {updated}")
        print(f"Already correct: {total - updated}")


if __name__ == '__main__':
    update_transaction_periods()
