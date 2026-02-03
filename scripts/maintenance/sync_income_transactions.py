"""
Script to sync existing income records with their transactions
Sets the bidirectional link between Income and Transaction
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.income import Income
from models.transactions import Transaction
from extensions import db

app = create_app()

with app.app_context():
    print("Syncing income records with transactions...")
    
    # Find all income records with transaction_id
    incomes_with_txn = Income.query.filter(Income.transaction_id.isnot(None)).all()
    
    synced = 0
    for income in incomes_with_txn:
        transaction = Transaction.query.get(income.transaction_id)
        if transaction:
            # Set bidirectional link
            transaction.income_id = income.id
            synced += 1
            print(f"  Synced: Income {income.id} <-> Transaction {transaction.id}")
    
    db.session.commit()
    print(f"\nCompleted! Synced {synced} income-transaction pairs.")
