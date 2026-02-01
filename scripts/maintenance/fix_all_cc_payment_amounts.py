"""
Fix credit card payment bank transaction amounts (comprehensive)
All CC payment bank transactions should be negative (debits - money out)
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction


def fix_cc_payment_amounts():
    """Fix all credit card payment bank transactions to have negative amounts"""
    app = create_app()
    
    with app.app_context():
        # Get all transactions that look like CC payments but are positive
        # 1. Transactions with credit_card_id that are positive
        # 2. Transactions with "Payment to" in description that are positive
        
        candidates = Transaction.query.filter(
            db.or_(
                # Has credit_card_id
                Transaction.credit_card_id.isnot(None),
                # Or has "Payment to" in description (typical CC payment pattern)
                Transaction.description.ilike('%payment to%')
            ),
            # And amount is positive (wrong - should be negative)
            Transaction.amount > 0
        ).all()
        
        total = len(candidates)
        fixed = 0
        
        print(f"\nFound {total} credit card payment transactions with POSITIVE amounts")
        print("=" * 70)
        
        for txn in candidates:
            print(f"Fixing ID {txn.id}: £{txn.amount:>8.2f} -> £{-abs(txn.amount):>8.2f}")
            print(f"  Description: {txn.description}")
            print(f"  Account: {txn.account_id} | CC: {txn.credit_card_id}")
            print(f"  Date: {txn.transaction_date}")
            print()
            
            # Fix the amount to negative
            txn.amount = -abs(txn.amount)
            fixed += 1
        
        # Commit all changes
        if fixed > 0:
            print("=" * 70)
            print(f"Committing changes...")
            db.session.commit()
            
            # Recalculate balances for affected accounts
            print(f"Recalculating account balances...")
            affected_accounts = set(txn.account_id for txn in candidates if txn.account_id)
            for account_id in affected_accounts:
                Transaction.recalculate_account_balance(account_id)
            
            db.session.commit()
            print("=" * 70)
        
        print(f"✓ Complete!")
        print(f"  Total fixed: {fixed}")
        
        if fixed > 0:
            print(f"  Account balances recalculated for {len(affected_accounts)} accounts")


if __name__ == '__main__':
    print("=" * 70)
    print("FIX CREDIT CARD PAYMENT AMOUNTS (COMPREHENSIVE)")
    print("=" * 70)
    print("\nThis will fix CC payment transactions that are incorrectly positive")
    print("(credits) to be negative (debits - money out of bank account).")
    
    response = input("\nContinue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        fix_cc_payment_amounts()
    else:
        print("Cancelled.")
