"""Delete future transactions for testing"""
import sys
from datetime import date
from app import create_app
from extensions import db
from models.credit_card_transactions import CreditCardTransaction

app = create_app()

with app.app_context():
    # Delete all Interest and Payment transactions from Feb 2026 onwards
    deleted = CreditCardTransaction.query.filter(
        CreditCardTransaction.date >= date(2026, 2, 1),
        CreditCardTransaction.transaction_type.in_(['Interest', 'Payment'])
    ).delete(synchronize_session=False)
    
    db.session.commit()
    
    print(f"✅ Deleted {deleted} future transactions")
