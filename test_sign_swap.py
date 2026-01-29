from app import create_app
from extensions import db
from models.transactions import Transaction

app = create_app()

with app.app_context():
    # Get a few transactions
    txns = Transaction.query.limit(10).all()
    
    print("Sample transactions after sign swap:")
    print("-" * 80)
    for t in txns:
        category = f"{t.category.sub_budget}" if t.category else "N/A"
        amount_type = "INCOME" if t.amount > 0 else "EXPENSE"
        print(f"ID: {t.id:4} | Date: {t.transaction_date} | Amount: £{t.amount:8.2f} | Type: {amount_type:8} | {category}")
    
    # Check totals
    all_txns = Transaction.query.all()
    income_count = len([t for t in all_txns if t.amount > 0])
    expense_count = len([t for t in all_txns if t.amount < 0])
    
    print("\n" + "=" * 80)
    print(f"Total transactions: {len(all_txns)}")
    print(f"Income transactions (positive amounts): {income_count}")
    print(f"Expense transactions (negative amounts): {expense_count}")
