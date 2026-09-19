from decimal import Decimal
from datetime import date

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from models.family import Family


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_transaction_index_renders_compact_filters(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/transactions?search=rent&is_paid=pending')

    assert response.status_code == 200
    assert b'transactionFilterDrawer' in response.data
    assert b'quick-filter-form' in response.data
    assert b'editPaidControl' in response.data
    assert b'Filtered by' in response.data
    assert b'rent' in response.data


def test_consolidated_index_renders_responsive_filters(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/transactions/consolidated?source=bank&is_paid=pending')

    assert response.status_code == 200
    assert b'consolidatedFilterDrawer' in response.data
    assert b'consolidated-filter-form' in response.data
    assert b'Filtered by' in response.data
    assert b'Bank' in response.data


def test_transaction_create_and_transfer_render_compact_editors(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    create_response = client.get('/transactions/create')
    transfer_response = client.get('/transactions/transfer')

    assert create_response.status_code == 200
    assert b'transaction-editor-page' in create_response.data
    assert b'transactionEditorForm' in create_response.data
    assert transfer_response.status_code == 200
    assert b'transfer-editor-page' in transfer_response.data
    assert b'transferEditorForm' in transfer_response.data


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

    response = client.get(f'/transactions/{transaction_id}/edit')
    assert response.status_code == 200
    assert b'transaction-editor-page' in response.data
    assert b'transaction-paid-control is-paid' in response.data
    assert b'Included in paid balances' in response.data

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


def test_transaction_create_rejects_references_from_another_family(app, family, user):
    account = Account(
        family_id=family.id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    other_family = Family(name='Other Family')
    db.session.add_all([account, other_family])
    db.session.flush()
    foreign_category = Category(
        family_id=other_family.id, name='Bills', head_budget='Home',
        sub_budget='Bills', category_type='expense'
    )
    db.session.add(foreign_category)
    db.session.commit()

    client = app.test_client()
    _login(client, user.id)
    response = client.post('/transactions/create', data={
        'account_id': str(account.id),
        'category_id': str(foreign_category.id),
        'amount': '-25.50',
        'transaction_date': '2026-01-15',
    })

    assert response.status_code == 302
    assert Transaction.query.count() == 0


def test_transaction_edit_rejects_references_from_another_family(app, family, user):
    account = Account(
        family_id=family.id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Bills', head_budget='Home',
        sub_budget='Bills', category_type='expense'
    )
    other_family = Family(name='Other Family')
    db.session.add_all([account, category, other_family])
    db.session.flush()
    foreign_category = Category(
        family_id=other_family.id, name='Other Bills', head_budget='Other',
        sub_budget='Bills', category_type='expense'
    )
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=-25, transaction_date=date(2026, 1, 15), description='Original'
    )
    db.session.add_all([foreign_category, transaction])
    db.session.commit()

    client = app.test_client()
    _login(client, user.id)
    response = client.post(f'/transactions/{transaction.id}/edit', data={
        'account_id': str(account.id),
        'category_id': str(foreign_category.id),
        'amount': '-30.00',
        'transaction_date': '2026-01-16',
        'description': 'Changed',
    })

    assert response.status_code == 302
    assert transaction.category_id == category.id
    assert transaction.description == 'Original'


def test_transaction_bulk_edit_rejects_references_from_another_family(app, family, user):
    account = Account(
        family_id=family.id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family.id, name='Bills', head_budget='Home',
        sub_budget='Bills', category_type='expense'
    )
    other_family = Family(name='Other Family')
    db.session.add_all([account, category, other_family])
    db.session.flush()
    foreign_category = Category(
        family_id=other_family.id, name='Other Bills', head_budget='Other',
        sub_budget='Bills', category_type='expense'
    )
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=-25, transaction_date=date(2026, 1, 15), description='Original'
    )
    db.session.add_all([foreign_category, transaction])
    db.session.commit()

    client = app.test_client()
    _login(client, user.id)
    response = client.post('/transactions/bulk-edit', data={
        'transaction_ids': str(transaction.id),
        'bulk_category_id': str(foreign_category.id),
    })

    assert response.status_code == 302
    assert transaction.category_id == category.id
