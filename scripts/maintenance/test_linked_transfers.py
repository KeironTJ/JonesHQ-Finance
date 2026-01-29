"""
Test if linked transfers are working and visible
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from extensions import db
from models.transactions import Transaction

def test_linked_transfers():
    """Test linked transfer functionality"""
    app = create_app()
    with app.app_context():
        # Find some linked transfer transactions
        linked_transfers = Transaction.query.filter(
            Transaction.linked_transaction_id != None,
            Transaction.payment_type == 'Transfer'
        ).limit(10).all()
        
        print(f"\nLinked Transfer Test")
        print("=" * 70)
        print(f"Found {len(linked_transfers)} linked transfer transactions\n")
        
        for txn in linked_transfers:
            linked = Transaction.query.get(txn.linked_transaction_id)
            
            print(f"Transaction ID: {txn.id}")
            print(f"  Account: {txn.account.name if txn.account else 'None'}")
            print(f"  Amount: £{txn.amount}")
            print(f"  Description: {txn.description}")
            print(f"  Linked ID: {txn.linked_transaction_id}")
            
            if linked:
                print(f"\n  Linked Transaction ID: {linked.id}")
                print(f"  Linked Account: {linked.account.name if linked.account else 'None'}")
                print(f"  Linked Amount: £{linked.amount}")
                print(f"  Linked Description: {linked.description}")
                print(f"  Amounts match (opposite): {txn.amount == -linked.amount}")
            else:
                print(f"  ⚠️  ERROR: Linked transaction {txn.linked_transaction_id} not found!")
            
            print("-" * 70)
        
        # Test if the field is accessible in query
        print("\n\nTesting field accessibility in queries...")
        test_txn = Transaction.query.filter(Transaction.linked_transaction_id != None).first()
        if test_txn:
            print(f"✓ Field accessible: linked_transaction_id = {test_txn.linked_transaction_id}")
            print(f"✓ Has attribute: {hasattr(test_txn, 'linked_transaction_id')}")
        else:
            print("✗ No transactions with linked_transaction_id found")

if __name__ == '__main__':
    test_linked_transfers()
