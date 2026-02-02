"""
Check what data exists for net worth calculations
"""
import sys
sys.path.insert(0, 'C:/Users/keiro/OneDrive/Documents/Programming/JonesHQ Finance')

from app import create_app
from extensions import db
from models.transactions import Transaction
from models.accounts import Account
from models.credit_card_transactions import CreditCardTransaction
from models.loan_payments import LoanPayment
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from sqlalchemy import func

app = create_app()

with app.app_context():
    print("=" * 80)
    print("ACCOUNT DATA CHECK")
    print("=" * 80)
    
    accounts = Account.query.filter_by(is_active=True).all()
    print(f"\nActive Accounts: {len(accounts)}")
    for acc in accounts:
        print(f"  - {acc.name} ({acc.account_type}): Balance = £{acc.balance}")
        
        # Check transactions for this account
        total_txns = Transaction.query.filter_by(account_id=acc.id).count()
        paid_txns = Transaction.query.filter_by(account_id=acc.id, is_paid=True).count()
        
        txns_with_balance = Transaction.query.filter(
            Transaction.account_id == acc.id,
            Transaction.running_balance.isnot(None)
        ).count()
        
        print(f"    Total transactions: {total_txns}")
        print(f"    Paid transactions: {paid_txns}")
        print(f"    Transactions with running_balance: {txns_with_balance}")
        
        if txns_with_balance > 0:
            # Get date range of transactions with balance
            first = Transaction.query.filter(
                Transaction.account_id == acc.id,
                Transaction.running_balance.isnot(None)
            ).order_by(Transaction.transaction_date.asc()).first()
            
            last = Transaction.query.filter(
                Transaction.account_id == acc.id,
                Transaction.running_balance.isnot(None)
            ).order_by(Transaction.transaction_date.desc()).first()
            
            if first and last:
                print(f"    Date range: {first.transaction_date} to {last.transaction_date}")
                print(f"    First balance: £{first.running_balance}, Last balance: £{last.running_balance}")
    
    print("\n" + "=" * 80)
    print("CREDIT CARD DATA CHECK")
    print("=" * 80)
    
    from models.credit_cards import CreditCard
    cards = CreditCard.query.filter_by(is_active=True).all()
    print(f"\nActive Credit Cards: {len(cards)}")
    for card in cards:
        total_txns = CreditCardTransaction.query.filter_by(credit_card_id=card.id).count()
        paid_txns = CreditCardTransaction.query.filter_by(credit_card_id=card.id, is_paid=True).count()
        
        latest_paid = CreditCardTransaction.query.filter_by(
            credit_card_id=card.id,
            is_paid=True
        ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).first()
        
        print(f"\n  - {card.card_name}")
        print(f"    Total transactions: {total_txns}")
        print(f"    Paid transactions: {paid_txns}")
        if latest_paid:
            print(f"    Latest paid: {latest_paid.date}, Balance: £{latest_paid.balance}")
    
    print("\n" + "=" * 80)
    print("LOAN DATA CHECK")
    print("=" * 80)
    
    from models.loans import Loan
    loans = Loan.query.filter_by(is_active=True).all()
    print(f"\nActive Loans: {len(loans)}")
    for loan in loans:
        total_payments = LoanPayment.query.filter_by(loan_id=loan.id).count()
        paid_payments = LoanPayment.query.filter_by(loan_id=loan.id, is_paid=True).count()
        
        latest_paid = LoanPayment.query.filter_by(
            loan_id=loan.id,
            is_paid=True
        ).order_by(LoanPayment.date.desc(), LoanPayment.id.desc()).first()
        
        print(f"\n  - {loan.name}")
        print(f"    Start date: {loan.start_date}")
        print(f"    Original value: £{loan.loan_value}")
        print(f"    Current balance: £{loan.current_balance}")
        print(f"    Total payments: {total_payments}")
        print(f"    Paid payments: {paid_payments}")
        if latest_paid:
            print(f"    Latest paid: {latest_paid.date}, Closing balance: £{latest_paid.closing_balance}")
    
    print("\n" + "=" * 80)
    print("PENSION DATA CHECK")
    print("=" * 80)
    
    pensions = Pension.query.filter_by(is_active=True).all()
    print(f"\nActive Pensions: {len(pensions)}")
    for pension in pensions:
        snapshots = PensionSnapshot.query.filter_by(pension_id=pension.id).count()
        print(f"\n  - {pension.provider}")
        print(f"    Current value: £{pension.current_value}")
        print(f"    Snapshots: {snapshots}")
        
        if snapshots > 0:
            first = PensionSnapshot.query.filter_by(pension_id=pension.id).order_by(
                PensionSnapshot.snapshot_date.asc()
            ).first()
            last = PensionSnapshot.query.filter_by(pension_id=pension.id).order_by(
                PensionSnapshot.snapshot_date.desc()
            ).first()
            print(f"    Date range: {first.snapshot_date} to {last.snapshot_date}")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total_accounts_with_balance = sum(1 for acc in accounts if Transaction.query.filter(
        Transaction.account_id == acc.id,
        Transaction.running_balance.isnot(None)
    ).count() > 0)
    
    print(f"\nAccounts with running_balance data: {total_accounts_with_balance}/{len(accounts)}")
    print(f"Credit cards with transactions: {sum(1 for c in cards if CreditCardTransaction.query.filter_by(credit_card_id=c.id).count() > 0)}/{len(cards)}")
    print(f"Loans with payments: {sum(1 for l in loans if LoanPayment.query.filter_by(loan_id=l.id).count() > 0)}/{len(loans)}")
    print(f"Pensions with snapshots: {sum(1 for p in pensions if PensionSnapshot.query.filter_by(pension_id=p.id).count() > 0)}/{len(pensions)}")
