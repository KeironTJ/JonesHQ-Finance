from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction
from models.vendors import Vendor
from models.plans import Plan, PlanItem
from models.family import Family


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


def test_credit_card_transaction_create_and_edit_manage_plan_link(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    category = Category(family_id=family.id, name='Gifts', head_budget='Lifestyle', sub_budget='Gifts', category_type='expense')
    plan = Plan(family_id=family.id, title='Christmas')
    item = PlanItem(family_id=family.id, plan=plan, title='Scooter')
    db.session.add_all([card, category, plan, item])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/credit-cards/{card.id}/transaction/add', data={
        'txn_date': '2026-09-21', 'txn_type': 'Purchase',
        'txn_item': 'Toy shop', 'txn_amount': '-70.00',
        'category_id': str(category.id), 'plan_item_id': str(item.id),
    })
    transaction = CreditCardTransaction.query.one()
    assert response.status_code == 302
    assert item.credit_card_transaction_id == transaction.id
    assert item.transaction_id is None

    response = client.post(f'/credit-cards/{card.id}/transaction/{transaction.id}/edit', data={
        'txn_date': '2026-09-21', 'txn_type': 'Purchase',
        'txn_item': 'Toy shop', 'txn_amount': '-70.00',
        'category_id': str(category.id), 'plan_item_id': '',
    })
    assert response.status_code == 302
    assert item.credit_card_transaction_id is None


def test_credit_card_transaction_create_and_edit_vendor(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    first_vendor = Vendor(family_id=family.id, name='First Vendor')
    second_vendor = Vendor(family_id=family.id, name='Second Vendor')
    db.session.add_all([card, first_vendor, second_vendor])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/credit-cards/{card.id}/transaction/add', data={
        'txn_date': '2026-09-21', 'txn_type': 'Purchase',
        'txn_item': 'First purchase', 'txn_amount': '-70.00',
        'vendor_id': str(first_vendor.id),
    })
    transaction = CreditCardTransaction.query.one()
    assert response.status_code == 302
    assert transaction.vendor_id == first_vendor.id

    response = client.post(f'/credit-cards/{card.id}/transaction/{transaction.id}/edit', data={
        'txn_date': '2026-09-21', 'txn_type': 'Purchase',
        'txn_item': 'Second purchase', 'txn_amount': '-70.00',
        'vendor_id': str(second_vendor.id),
    })
    assert response.status_code == 302
    assert transaction.vendor_id == second_vendor.id


def test_credit_card_detail_renders_plan_link_action_and_badge(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    transaction = CreditCardTransaction(
        family_id=family.id, credit_card=card, date=date.today(),
        transaction_type='Purchase', item='Toy shop', amount=Decimal('-20.00'),
    )
    vendor = Vendor(family_id=family.id, name='Toy Shop')
    transaction.vendor = vendor
    plan = Plan(family_id=family.id, title='Christmas')
    item = PlanItem(family_id=family.id, plan=plan, title='Gift', credit_card_transaction=transaction)
    db.session.add_all([card, transaction, plan, item])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.get(f'/credit-cards/{card.id}?is_paid=pending')

    assert response.status_code == 200
    assert b'ccPlanLinkModal' in response.data
    assert b'Christmas' in response.data
    assert b'Gift' in response.data
    assert b'Toy Shop' in response.data


def test_credit_card_plan_link_rejects_foreign_item(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    transaction = CreditCardTransaction(
        family_id=family.id, credit_card=card, date=date.today(),
        transaction_type='Purchase', item='Toy shop', amount=Decimal('-20.00'),
    )
    other_family = Family(name='Other Family')
    db.session.add_all([card, transaction, other_family])
    db.session.flush()
    foreign_plan = Plan(family_id=other_family.id, title='Private')
    foreign_item = PlanItem(family_id=other_family.id, plan=foreign_plan, title='Private gift')
    db.session.add(foreign_plan)
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/credit-cards/transaction/{transaction.id}/link-plan', data={'item_id': str(foreign_item.id)})

    assert response.status_code == 404
    assert foreign_item.credit_card_transaction_id is None


def test_deleting_credit_card_transaction_clears_plan_link(app, family, user):
    card = CreditCard(
        family_id=family.id, card_name='Route Card', annual_apr=24,
        monthly_apr=2, min_payment_percent=2, credit_limit=5000,
        current_balance=0, available_credit=5000, is_active=True,
    )
    transaction = CreditCardTransaction(
        family_id=family.id, credit_card=card, date=date.today(),
        transaction_type='Purchase', item='Toy shop', amount=Decimal('-20.00'),
    )
    plan = Plan(family_id=family.id, title='Christmas')
    item = PlanItem(family_id=family.id, plan=plan, title='Gift', credit_card_transaction=transaction)
    db.session.add_all([card, transaction, plan, item])
    db.session.commit()
    client = app.test_client()
    _login(client, user.id)

    response = client.post(f'/credit-cards/{card.id}/transaction/{transaction.id}/delete')

    assert response.status_code == 302
    assert item.credit_card_transaction_id is None


