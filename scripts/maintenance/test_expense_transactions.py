import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app import create_app
from models.expenses import Expense
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction

app = create_app()
app.app_context().push()

# Check first few expenses
expenses = Expense.query.limit(5).all()

print("Expense Transaction Verification:")
print("="*80)

for exp in expenses:
    print(f"\nExpense #{exp.id}: {exp.date} - {exp.description} - £{exp.total_cost}")
    print(f"  Credit Card: {exp.credit_card_id}")
    print(f"  Submitted: {exp.submitted}")
    
    if exp.bank_transaction_id:
        txn = Transaction.query.get(exp.bank_transaction_id)
        if txn:
            print(f"  ✓ Bank Transaction: #{txn.id} - {txn.description} - £{txn.amount} - {txn.payment_type}")
        else:
            print(f"  ✗ Bank Transaction ID {exp.bank_transaction_id} not found")
    
    if exp.credit_card_transaction_id:
        cc_txn = CreditCardTransaction.query.get(exp.credit_card_transaction_id)
        if cc_txn:
            print(f"  ✓ CC Transaction: #{cc_txn.id} - {cc_txn.item} - £{cc_txn.amount} - {cc_txn.transaction_type}")
        else:
            print(f"  ✗ CC Transaction ID {exp.credit_card_transaction_id} not found")
    
    if not exp.bank_transaction_id and not exp.credit_card_transaction_id:
        print(f"  ⚠ No transactions linked!")

print("\n" + "="*80)

# Count totals
total_expenses = Expense.query.count()
with_bank = Expense.query.filter(Expense.bank_transaction_id != None).count()
with_cc = Expense.query.filter(Expense.credit_card_transaction_id != None).count()

print(f"\nSummary:")
print(f"  Total Expenses: {total_expenses}")
print(f"  With Bank Transactions: {with_bank}")
print(f"  With CC Transactions: {with_cc}")
