from app import create_app
from services.expense_sync_service import ExpenseSyncService
from models.expenses import Expense

app = create_app()
app.app_context().push()

q = Expense.query.filter((Expense.credit_card_id != None) | (Expense.reimbursed == True)).all()
print('Expenses to reconcile:', len(q))
count = 0
for exp in q:
    try:
        ExpenseSyncService.reconcile(exp.id)
        count += 1
    except Exception as e:
        print('Failed for', exp.id, e)

print('Reconciled:', count)
