"""Investigate March 2027 Spike"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.networth_service import NetWorthService
from datetime import date
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction
from models.loan_payments import LoanPayment

app = create_app()

with app.app_context():
    print("=" * 80)
    print("INVESTIGATING MARCH 2027 SPIKE")
    print("=" * 80)
    print()
    
    # Get timeline around March 2027
    timeline = NetWorthService.get_monthly_timeline(2027, 1, 6)
    
    print("Timeline around March 2027:")
    print("-" * 80)
    for month_data in timeline:
        print(f"{month_data['month_label']}: "
              f"Assets=£{month_data['total_assets']:,.2f}, "
              f"Liabilities=£{month_data['total_liabilities']:,.2f}, "
              f"Net Worth=£{month_data['net_worth']:,.2f}")
    print()
    
    # Get detailed breakdown for Feb, Mar, Apr 2027
    print("=" * 80)
    print("DETAILED BREAKDOWN")
    print("=" * 80)
    
    for month in [2, 3, 4]:
        target_date = date(2027, month, 28)
        data = NetWorthService.calculate_networth_at_date(target_date)
        
        print(f"\n{target_date.strftime('%B %Y')} (at {target_date}):")
        print("-" * 80)
        print(f"  Cash:        £{data['cash']:,.2f}")
        print(f"  Savings:     £{data['savings']:,.2f}")
        print(f"  Pensions:    £{data['pensions_value']:,.2f}")
        print(f"  TOTAL ASSETS: £{data['total_assets']:,.2f}")
        print()
        print(f"  Credit Cards: £{data['credit_cards']:,.2f}")
        print(f"  Loans:        £{data['loans']:,.2f}")
        print(f"  Mortgage:     £{data['mortgage']:,.2f}")
        print(f"  TOTAL LIABILITIES: £{data['total_liabilities']:,.2f}")
        print()
        print(f"  NET WORTH: £{data['net_worth']:,.2f}")
    
    # Check for unusual transactions in March 2027
    print("\n" + "=" * 80)
    print("CHECKING FOR UNUSUAL TRANSACTIONS IN MARCH 2027")
    print("=" * 80)
    
    march_start = date(2027, 3, 1)
    march_end = date(2027, 3, 31)
    
    # Check account transactions
    print("\nAccount Transactions in March 2027:")
    march_txns = Transaction.query.filter(
        Transaction.transaction_date >= march_start,
        Transaction.transaction_date <= march_end
    ).order_by(Transaction.amount.desc()).limit(10).all()
    
    if march_txns:
        for txn in march_txns:
            print(f"  {txn.transaction_date}: £{txn.amount:,.2f} - {txn.description} (Paid: {txn.is_paid})")
    else:
        print("  No transactions found")
    
    # Check credit card transactions
    print("\nCredit Card Transactions in March 2027:")
    march_cc = CreditCardTransaction.query.filter(
        CreditCardTransaction.date >= march_start,
        CreditCardTransaction.date <= march_end
    ).order_by(CreditCardTransaction.amount.desc()).limit(10).all()
    
    if march_cc:
        for txn in march_cc:
            print(f"  {txn.date}: £{txn.amount:,.2f} (Balance: £{txn.balance:,.2f}) (Paid: {txn.is_paid})")
    else:
        print("  No credit card transactions found")
    
    # Check loan payments
    print("\nLoan Payments in March 2027:")
    march_loans = LoanPayment.query.filter(
        LoanPayment.date >= march_start,
        LoanPayment.date <= march_end
    ).order_by(LoanPayment.date).all()
    
    if march_loans:
        for pmt in march_loans:
            print(f"  {pmt.date}: Payment=£{pmt.payment_amount:,.2f}, "
                  f"Closing=£{pmt.closing_balance:,.2f} (Paid: {pmt.is_paid})")
    else:
        print("  No loan payments found")
    
    print("\n" + "=" * 80)
