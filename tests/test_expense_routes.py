from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.expenses import Expense
from models.transactions import Transaction


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_expense_index_route_loads_for_authenticated_family(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/expenses')

    assert response.status_code == 200
    assert b'Expenses' in response.data or b'expense' in response.data.lower()


def test_expense_mileage_route_loads_empty_state(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/expenses/mileage')

    assert response.status_code == 200


def test_delete_expense_with_linked_transaction(app, family, user):
    account = Account(name='Current Account', account_type='Current', family_id=family.id)
    category = Category(name='Travel', category_type='Expense', family_id=family.id)
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=Decimal('-18.00'),
        transaction_date=date(2026, 4, 15),
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id,
        date=date(2026, 4, 15),
        description='Client travel',
        expense_type='Mileage',
        cost=Decimal('18.00'),
        total_cost=Decimal('18.00'),
        bank_transaction_id=transaction.id,
    )
    db.session.add(expense)
    db.session.commit()
    expense_id = expense.id
    transaction_id = transaction.id
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/expenses/delete/{expense_id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Expense deleted' in response.data
    assert db.session.get(Expense, expense_id) is None
    assert Transaction.query.filter_by(id=transaction_id).first() is None
