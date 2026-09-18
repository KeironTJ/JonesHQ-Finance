from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_transaction_routes_create_edit_delete(app, family, user):
    family_id = family.id
    user_id = user.id
    account = Account(
        family_id=family_id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family_id, name='Bills', head_budget='Home',
        sub_budget='Bills', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.commit()
    account_id = account.id
    category_id = category.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post('/transactions/create', data={
        'account_id': str(account_id),
        'category_id': str(category_id),
        'amount': '-25.50',
        'transaction_date': '2026-01-15',
        'description': 'Created transaction',
        'item': 'Initial item',
        'assigned_to': 'Household',
        'payment_type': 'Direct Debit',
        'is_paid': '1',
    })
    assert response.status_code == 302
    transaction = Transaction.query.one()
    transaction_id = transaction.id
    assert transaction.family_id == family_id
    assert transaction.amount == Decimal('-25.50')

    response = client.post(f'/transactions/{transaction_id}/edit', data={
        'account_id': str(account_id),
        'category_id': str(category_id),
        'amount': '-30.00',
        'transaction_date': '2026-02-15',
        'description': 'Updated transaction',
        'item': 'Updated item',
        'assigned_to': 'Household',
        'payment_type': 'Direct Debit',
        'is_paid': '1',
        'txn_fixed': '1',
    })
    assert response.status_code == 302
    transaction = db.session.get(Transaction, transaction_id)
    assert transaction.amount == Decimal('-30.00')
    assert transaction.description == 'Updated transaction'
    assert transaction.year_month == '2026-02'

    response = client.post(f'/{transaction_id}/delete')
    assert response.status_code == 302
    assert db.session.get(Transaction, transaction_id) is None
