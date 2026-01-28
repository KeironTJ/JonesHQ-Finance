from app import create_app
from extensions import db
from models import CreditCardTransaction
from datetime import date

app = create_app()

with app.app_context():
    today = date.today()
    
    # Get all past transactions that are not marked as paid
    past_unpaid = CreditCardTransaction.query.filter(
        CreditCardTransaction.date < today,
        CreditCardTransaction.is_paid == False
    ).all()
    
    print(f"Found {len(past_unpaid)} past unpaid transactions")
    
    # Mark them as paid
    for txn in past_unpaid:
        txn.is_paid = True
        print(f"  Marking as paid: {txn.date} - {txn.transaction_type} - {txn.item}")
    
    db.session.commit()
    
    print(f"\nMarked {len(past_unpaid)} past transactions as paid")
    
    # Verify
    still_unpaid = CreditCardTransaction.query.filter(
        CreditCardTransaction.date < today,
        CreditCardTransaction.is_paid == False
    ).count()
    
    print(f"Past unpaid transactions remaining: {still_unpaid}")
