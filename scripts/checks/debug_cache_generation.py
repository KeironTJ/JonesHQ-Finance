"""Debug cache generation"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from datetime import date
from dateutil.relativedelta import relativedelta
from models.transactions import Transaction
from extensions import db

app = create_app()

with app.app_context():
    print("Debugging cache generation logic:")
    print()
    
    # Find earliest transaction
    earliest = db.session.query(db.func.min(Transaction.transaction_date)).scalar()
    print(f"Earliest transaction: {earliest}")
    
    # Calculate future date
    today = date.today()
    future_date = today + relativedelta(months=12)
    print(f"Today: {today}")
    print(f"12 months from today: {future_date}")
    
    # Calculate months difference
    start_date = date(earliest.year, earliest.month, 1)
    months_diff = (future_date.year - start_date.year) * 12 + (future_date.month - start_date.month) + 1
    
    print(f"\nStart date (earliest txn month): {start_date}")
    print(f"End date (12 months from now): {future_date}")
    print(f"Months to calculate: {months_diff}")
    
    # Show what months would be generated
    current = start_date
    print(f"\nMonths that should be generated:")
    for i in range(min(months_diff, 5)):
        print(f"  {i+1}. {current.strftime('%Y-%m')}")
        current = current + relativedelta(months=1)
    print(f"  ...")
    
    # Show last few months
    current = start_date + relativedelta(months=months_diff-3)
    for i in range(3):
        print(f"  {months_diff-2+i}. {current.strftime('%Y-%m')}")
        current = current + relativedelta(months=1)
