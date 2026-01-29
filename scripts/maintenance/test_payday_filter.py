import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.transactions import Transaction
from services.payday_service import PaydayService

app = create_app()

with app.app_context():
    # Test transaction payday_period
    txn = Transaction.query.first()
    print(f"Sample transaction: {txn.transaction_date} -> Payday Period: {txn.payday_period}")
    
    # Test recent periods
    periods = PaydayService.get_recent_periods(5, include_future=True)
    print(f"\nPayday periods for filter dropdown:")
    for p in periods:
        print(f"  {p['label']}: {p['display_name']}")
    
    # Count transactions with payday_period
    total = Transaction.query.count()
    with_period = Transaction.query.filter(Transaction.payday_period != None).count()
    print(f"\nTransactions with payday_period: {with_period}/{total}")
