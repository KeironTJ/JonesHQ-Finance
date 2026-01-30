"""Check transaction amount format"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.transactions import Transaction

app = create_app()

with app.app_context():
    # Get some sample expense transactions
    transactions = Transaction.query.filter(Transaction.is_forecasted == False).limit(10).all()
    
    print("Sample transaction amounts:")
    for t in transactions:
        cat_name = t.category.name if t.category else 'N/A'
        print(f"  {t.transaction_date} | {cat_name} | Amount: {t.amount}")
    
    # Check income vs expense
    income_trans = Transaction.query.filter(Transaction.category_id.in_([1, 2])).first()
    if income_trans:
        print(f"\nSample income transaction: {income_trans.amount}")
    
    # Check general expense
    expense_trans = Transaction.query.filter(Transaction.category_id > 2).first()
    if expense_trans:
        print(f"Sample expense transaction: {expense_trans.amount}")
