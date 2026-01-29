"""
Link existing transfer transactions together
Finds pairs of transfer transactions and links them via linked_transaction_id
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.transactions import Transaction
from datetime import timedelta

def link_transfers():
    """Find and link transfer transaction pairs"""
    app = create_app()
    with app.app_context():
        # Find all transfer transactions that aren't already linked
        transfers = Transaction.query.filter(
            Transaction.payment_type == 'Transfer',
            Transaction.linked_transaction_id == None
        ).order_by(Transaction.transaction_date, Transaction.id).all()
        
        print(f"\nLinking Transfer Transactions")
        print("=" * 70)
        print(f"Found {len(transfers)} unlinked transfer transactions\n")
        
        linked_count = 0
        
        # Process each transfer
        for txn in transfers:
            if txn.linked_transaction_id:
                continue  # Already linked
            
            # Look for matching transfer on same date with opposite amount
            # Must be in different account
            matching = Transaction.query.filter(
                Transaction.id != txn.id,
                Transaction.payment_type == 'Transfer',
                Transaction.linked_transaction_id == None,
                Transaction.transaction_date == txn.transaction_date,
                Transaction.account_id != txn.account_id,
                Transaction.amount == -txn.amount  # Opposite sign
            ).first()
            
            if matching:
                # Link them together
                txn.linked_transaction_id = matching.id
                matching.linked_transaction_id = txn.id
                
                from_account = txn.account.name if txn.account else 'Unknown'
                to_account = matching.account.name if matching.account else 'Unknown'
                
                print(f"✓ Linked: {txn.transaction_date} | £{abs(txn.amount):.2f}")
                print(f"  From: {from_account} (ID: {txn.id})")
                print(f"  To:   {to_account} (ID: {matching.id})")
                
                linked_count += 2
        
        db.session.commit()
        
        print("\n" + "=" * 70)
        print(f"Linked {linked_count // 2} transfer pairs ({linked_count} transactions)")
        
        # Check for unmatched transfers
        unmatched = Transaction.query.filter(
            Transaction.payment_type == 'Transfer',
            Transaction.linked_transaction_id == None
        ).count()
        
        if unmatched > 0:
            print(f"\n⚠️  Warning: {unmatched} transfer transactions remain unlinked")
            print("   These may be standalone transfers or have non-matching pairs")

if __name__ == '__main__':
    link_transfers()
