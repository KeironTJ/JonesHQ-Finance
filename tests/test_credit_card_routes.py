from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_credit_card_payment_route_creates_linked_bank_transaction(
    app, family, user
):
    family_id = family.id
    user_id = user.id
    account = Account(
        family_id=family_id, name='Current', account_type='Joint',
        balance=0, is_active=True
    )
    card = CreditCard(
        family_id=family_id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True
    )
    category = Category(
        family_id=family_id, name='Card Payment', head_budget='Credit Cards',
        sub_budget='Route Card', category_type='expense'
    )
    db.session.add_all([account, card, category])
    db.session.commit()
    card_id = card.id
    account_id = account.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f'/credit-cards/{card_id}/transaction/add', data={
        'txn_date': '2026-01-15',
        'txn_type': 'Payment',
        'txn_item': 'Monthly payment',
        'txn_amount': '125',
        'category_id': '',
        'account_id': str(account_id),
        'txn_fixed': '1',
        'txn_paid': '1',
        'is_recurring': '',
        'occurrences': '1',
    })

    assert response.status_code == 302
    payment = CreditCardTransaction.query.one()
    bank_transaction = db.session.get(Transaction, payment.bank_transaction_id)
    assert payment.family_id == family_id
    assert bank_transaction is not None
    assert bank_transaction.amount == Decimal('-125.00')
    assert bank_transaction.account_id == account.id


