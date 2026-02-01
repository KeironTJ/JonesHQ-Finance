"""
Fix transfer transaction amounts
Transfers were created with reversed signs - fix them
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from extensions import db
from models.transactions import Transaction


def fix_transfer_amounts():
    """Fix all transfer transactions to have correct signs"""
    app = create_app()
    
    with app.app_context():
        # Get all transfer transactions
        transfers = Transaction.query.filter(
            Transaction.payment_type == 'Transfer'
        ).all()
        
        total = len(transfers)
        fixed = 0
        
        print(f"\nFound {total} transfer transactions")
        print("=" * 70)
        
        # Group by linked pairs
        processed_ids = set()
        
        for txn in transfers:
            if txn.id in processed_ids:
                continue
            
            # Find the linked transaction
            linked = None
            if txn.linked_transaction_id:
                linked = Transaction.query.get(txn.linked_transaction_id)
            
            if not linked:
                print(f"⚠ Transaction {txn.id} has no linked transfer - skipping")
                continue
            
            # Determine which is FROM and which is TO based on description
            if "Transfer to" in txn.description:
                from_txn = txn
                to_txn = linked
            elif "Transfer from" in txn.description:
                to_txn = txn
                from_txn = linked
            else:
                print(f"⚠ Transaction {txn.id} doesn't match transfer pattern - skipping")
                continue
            
            # Check if they're already correct
            # FROM should be negative, TO should be positive
            if from_txn.amount < 0 and to_txn.amount > 0:
                # Already correct
                processed_ids.add(from_txn.id)
                processed_ids.add(to_txn.id)
                continue
            
            # They're backwards - flip them
            print(f"\nFixing transfer pair:")
            print(f"  FROM (ID {from_txn.id}): £{from_txn.amount:>8.2f} -> £{-abs(from_txn.amount):>8.2f}")
            print(f"    Description: {from_txn.description}")
            print(f"    Account: {from_txn.account_id}")
            print(f"  TO (ID {to_txn.id}):   £{to_txn.amount:>8.2f} -> £{abs(to_txn.amount):>8.2f}")
            print(f"    Description: {to_txn.description}")
            print(f"    Account: {to_txn.account_id}")
            
            # Fix the amounts
            from_txn.amount = -abs(from_txn.amount)  # FROM should be negative (money out)
            to_txn.amount = abs(to_txn.amount)       # TO should be positive (money in)
            
            processed_ids.add(from_txn.id)
            processed_ids.add(to_txn.id)
            fixed += 2
        
        # Commit all changes
        if fixed > 0:
            print("\n" + "=" * 70)
            print(f"Committing changes...")
            db.session.commit()
            
            # Recalculate balances for affected accounts
            print(f"Recalculating account balances...")
            affected_accounts = set(txn.account_id for txn in transfers if txn.account_id)
            for account_id in affected_accounts:
                Transaction.recalculate_account_balance(account_id)
            
            db.session.commit()
            print("=" * 70)
        
        print(f"✓ Complete!")
        print(f"  Total transfers: {total}")
        print(f"  Fixed: {fixed}")
        
        if fixed > 0:
            print(f"  Account balances recalculated for {len(affected_accounts)} accounts")


if __name__ == '__main__':
    print("=" * 70)
    print("FIX TRANSFER TRANSACTION AMOUNTS")
    print("=" * 70)
    print("\nThis will fix transfer transactions that have reversed signs.")
    print("FROM account should be negative (money out)")
    print("TO account should be positive (money in)")
    
    response = input("\nContinue? (yes/no): ")
    
    if response.lower() in ['yes', 'y']:
        fix_transfer_amounts()
    else:
        print("Cancelled.")
