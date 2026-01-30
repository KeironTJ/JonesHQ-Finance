"""
Script to reconcile all existing expenses - creates missing payment transactions.
Run this after enabling the expense sync service to backfill transactions.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.expenses import Expense
from services.expense_sync_service import ExpenseSyncService

def reconcile_all_expenses():
    """Reconcile all existing expenses to create payment transactions"""
    app = create_app()
    
    with app.app_context():
        expenses = Expense.query.order_by(Expense.date).all()
        
        print(f"Found {len(expenses)} expenses to reconcile...")
        print("="*60)
        
        success_count = 0
        error_count = 0
        
        for exp in expenses:
            try:
                print(f"Processing: {exp.date} - {exp.description} - £{exp.total_cost}", end=" ... ")
                ExpenseSyncService.reconcile(exp.id)
                print("✓")
                success_count += 1
            except Exception as e:
                print(f"✗ Error: {str(e)}")
                error_count += 1
        
        print("="*60)
        print(f"\nResults:")
        print(f"  ✓ Success: {success_count}")
        print(f"  ✗ Errors: {error_count}")
        print(f"\nPayment transactions created for all expenses!")

if __name__ == '__main__':
    reconcile_all_expenses()
