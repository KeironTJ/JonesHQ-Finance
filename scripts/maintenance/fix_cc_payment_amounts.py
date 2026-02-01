"""
Fix credit card payment bank transaction amounts
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
        # Get all bank transactions linked to credit cards
        cc_payment_transactions = Transaction.query.filter(
            Transaction.credit_card_id.isnot(None),
            Transaction.payment_type == 'Card Payment'
        ).all()
        
        total = len(cc_payment_transactions)
        fixed = 0
        already_correct = 0
        
        print(f"\nFound {total} credit card payment bank transactions")
        print("-" * 50)
        
        for txn in cc_payment_transactions:
            # CC payments from bank accounts should always be negative (money out)
            if txn.amount > 0:
                print(f"Fixing transaction {txn.id}: £{txn.amount:.2f} -> £{-abs(txn.amount):.2f}")
                txn.amount = -abs(txn.amount)
                fixed += 1
            else:
                already_correct += 1
        
        # Commit all changes
        if fixed > 0:
            print(f"\nCommitting changes...")
            db.session.commit()
            
            # Recalculate balances for affected accounts
            print(f"Recalculating account balances...")
            affected_accounts = set(txn.account_id for txn in cc_payment_transactions if txn.account_id)
            for account_id in affected_accounts:
                Transaction.recalculate_account_balance(account_id)
            
            db.session.commit()
        
        print("-" * 50)
        print(f"✓ Complete!")
        print(f"  Total CC payment transactions: {total}")
        print(f"  Fixed (were positive): {fixed}")
        print(f"  Already correct (were negative): {already_correct}")
        
        if fixed > 0:
            print(f"\n  Account balances recalculated for {len(affected_accounts)} accounts")


if __name__ == '__main__':
    print("=" * 50)
    print("Fix Credit Card Payment Bank Transaction Amounts")
    print("=" * 50)
    
    response = input("\nThis will fix CC payment amounts to be negative (debits).\nContinue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        fix_cc_payment_amounts()
    else:
        print("Cancelled.")
