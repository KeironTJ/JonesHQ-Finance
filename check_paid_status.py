"""Check and fix is_paid status on transactions"""
from app import create_app
from extensions import db
from models.credit_card_transactions import CreditCardTransaction

app = create_app()

with app.app_context():
    # Get all transactions
    all_txns = CreditCardTransaction.query.all()
    paid_count = sum(1 for t in all_txns if t.is_paid)
    
    print(f"Total transactions: {len(all_txns)}")
    print(f"Marked as paid: {paid_count}")
    print(f"Marked as unpaid: {len(all_txns) - paid_count}")
    
    if paid_count > 0:
        print("\n" + "="*70)
        response = input(f"Set all {paid_count} paid transactions to unpaid? (yes/no): ")
        if response.lower() == 'yes':
            for txn in all_txns:
                if txn.is_paid:
                    txn.is_paid = False
            db.session.commit()
            print(f"✅ Updated {paid_count} transactions to unpaid status")
        else:
            print("❌ No changes made")
