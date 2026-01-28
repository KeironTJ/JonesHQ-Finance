"""Debug payday calculations"""
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.payday_service import PaydayService
from models.transactions import Transaction
from models.accounts import Account
from datetime import date

app = create_app()

with app.app_context():
    # Get first Joint account
    joint_account = Account.query.filter_by(account_type='Joint', is_active=True).first()
    
    if not joint_account:
        print("No Joint account found")
        exit(1)
    
    print(f"Analyzing account: {joint_account.name} (ID: {joint_account.id})")
    print(f"Stored balance: £{joint_account.balance}")
    print()
    
    # Get all transactions for this account
    all_txns = Transaction.query.filter_by(
        account_id=joint_account.id
    ).order_by(Transaction.transaction_date).all()
    
    print(f"Total transactions: {len(all_txns)}")
    
    # Calculate balance manually
    balance = Decimal('0.00')
    income_total = Decimal('0.00')
    expense_total = Decimal('0.00')
    
    for txn in all_txns[:10]:  # Show first 10
        old_balance = balance
        if txn.amount < 0:
            # Income
            income_total += abs(Decimal(str(txn.amount)))
            balance += abs(Decimal(str(txn.amount)))
            txn_type = "INCOME"
        else:
            # Expense
            expense_total += Decimal(str(txn.amount))
            balance -= Decimal(str(txn.amount))
            txn_type = "EXPENSE"
        
        print(f"{txn.transaction_date} | {txn_type:8} | Amount: £{abs(float(txn.amount)):8.2f} | Balance: £{old_balance:8.2f} -> £{balance:8.2f} | {txn.description[:30]}")
    
    print(f"\n... ({len(all_txns) - 10} more transactions)")
    
    # Calculate final balance
    final_balance = Decimal('0.00')
    for txn in all_txns:
        if txn.amount < 0:
            final_balance += abs(Decimal(str(txn.amount)))
        else:
            final_balance -= Decimal(str(txn.amount))
    
    print(f"\nFinal calculated balance: £{final_balance:.2f}")
    print(f"Total income: £{income_total:.2f}")
    print(f"Total expense: £{expense_total:.2f}")
    print(f"Net: £{income_total - expense_total:.2f}")
    print()
    
    # Test payday service
    print("=" * 80)
    print("Testing Payday Service")
    print("=" * 80)
    
    payday_day = 15
    start_date = date(2026, 1, 15)
    end_date = date(2026, 2, 14)
    
    print(f"Period: {start_date} to {end_date}")
    
    result = PaydayService.calculate_period_balances(
        joint_account.id,
        start_date,
        end_date,
        include_unpaid=True
    )
    
    print(f"Opening Balance: £{result['opening_balance']:.2f}")
    print(f"Rolling Balance: £{result['rolling_balance']:.2f}")
    print(f"Min Balance: £{result['min_balance']:.2f}")
    print(f"Max Extra Spend: £{result['max_extra_spend']:.2f}")
