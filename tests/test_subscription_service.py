from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from werkzeug.datastructures import MultiDict

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.subscriptions import Subscription
from models.transactions import Transaction
from models.users import User
from services.finance.subscription_service import SubscriptionService
from utils.db_helpers import family_query


def _add_bank_target(family):
    account = Account(
        family_id=family.id,
        name='Current Account',
        account_type='Joint',
        balance=Decimal('0.00'),
        is_active=True,
    )
    category = Category(
        family_id=family.id,
        name='Streaming',
        head_budget='Entertainment',
        sub_budget='Streaming',
        category_type='expense',
    )
    db.session.add_all([account, category])
    db.session.commit()
    return account, category


def _bank_form(account, category, *, amount='12.99', end_date='', horizon='1'):
    return MultiDict({
        'name': 'Stream service',
        'amount': amount,
        'target_type': 'bank',
        'account_id': str(account.id),
        'credit_card_id': '',
        'category_id': str(category.id),
        'vendor_id': '',
        'frequency': 'monthly',
        'start_date': date.today().isoformat(),
        'end_date': end_date,
        'horizon_years': horizon,
    })


def test_subscription_updates_and_cancellation_leave_paid_bank_entries_untouched(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.subscription_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    account, category = _add_bank_target(family)
    end_date = (date.today() + relativedelta(months=2)).isoformat()

    subscription = SubscriptionService.create(
        _bank_form(account, category, end_date=end_date)
    )
    db.session.flush()
    entries = Transaction.query.filter_by(subscription_id=subscription.id).order_by(
        Transaction.transaction_date
    ).all()
    assert len(entries) == 3
    assert all(entry.amount == Decimal('-12.99') for entry in entries)

    paid_entry = entries[0]
    paid_entry.is_paid = True
    paid_amount = paid_entry.amount
    db.session.flush()

    updated_end_date = (date.today() + relativedelta(months=3)).isoformat()
    SubscriptionService.update(
        subscription.id,
        _bank_form(
            account, category, amount='18.50', end_date=updated_end_date
        ),
    )
    db.session.flush()

    assert paid_entry.is_paid is True
    assert paid_entry.amount == paid_amount
    pending = Transaction.query.filter_by(
        subscription_id=subscription.id, is_paid=False
    ).all()
    assert len(pending) == 3
    assert all(entry.amount == Decimal('-18.50') for entry in pending)

    SubscriptionService.set_active(subscription.id, False)
    paused_end_date = (date.today() + relativedelta(months=4)).isoformat()
    SubscriptionService.update(
        subscription.id,
        _bank_form(
            account, category, amount='21.00', end_date=paused_end_date
        ),
    )
    pending = Transaction.query.filter_by(
        subscription_id=subscription.id, is_paid=False
    ).all()
    assert len(pending) == 3
    assert all(entry.amount == Decimal('-21.00') for entry in pending)

    SubscriptionService.cancel(subscription.id)
    db.session.flush()
    assert Transaction.query.filter_by(
        subscription_id=subscription.id, is_paid=False
    ).count() == 0
    assert Transaction.query.filter_by(
        subscription_id=subscription.id, is_paid=True
    ).count() == 1


def test_five_year_horizon_bounds_monthly_schedule(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)
    subscription = Subscription(
        family_id=family.id,
        name='Stream service',
        amount=Decimal('-12.99'),
        frequency='monthly',
        start_date=date.today(),
        horizon_years=5,
        account_id=account.id,
        category_id=category.id,
    )

    scheduled = list(
        SubscriptionService._scheduled_dates(subscription, date.today())
    )
    horizon_end = date.today() + relativedelta(years=5)
    assert scheduled[0] == date.today()
    assert scheduled[-1] <= horizon_end
    assert len(scheduled) <= 61


def test_subscription_visibility_tracks_private_target_owner(
    app, family, user, monkeypatch
):
    other_user = User(
        email='member@example.com',
        name='Other Member',
        family_id=family.id,
        role='member',
    )
    other_user.set_password('TestPass1!')
    db.session.add(other_user)
    db.session.flush()
    account, category = _add_bank_target(family)
    account.owner_id = user.id
    db.session.flush()

    active_user_id = {'value': user.id}
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'utils.db_helpers.get_current_user_id',
        lambda: active_user_id['value'],
    )
    monkeypatch.setattr(
        'services.finance.subscription_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    subscription = SubscriptionService.create(_bank_form(account, category))
    db.session.flush()

    assert family_query(Subscription).filter_by(id=subscription.id).count() == 1
    active_user_id['value'] = other_user.id
    assert family_query(Subscription).filter_by(id=subscription.id).count() == 0

    account.owner_id = other_user.id
    db.session.flush()
    assert family_query(Subscription).filter_by(id=subscription.id).count() == 1


def test_subscription_templates_compile(app):
    app.jinja_env.get_template('transactions/subscriptions.html')
    app.jinja_env.get_template('transactions/subscription_form.html')
    app.jinja_env.get_template('transactions/transactions.html')
    app.jinja_env.get_template('credit_cards/detail.html')


def test_subscription_routes_create_and_list_rule(app, family, user):
    account, category = _add_bank_target(family)
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True

    response = client.get('/transactions/subscriptions')
    assert response.status_code == 200
    response = client.get('/transactions/subscriptions/create')
    assert response.status_code == 200
    assert b"openQuickAddVendor('vendor_id')" in response.data
    assert b'id="quickAddVendorModal"' in response.data
    assert b'js/quick_add_vendor.js' in response.data
    vendor_response = client.post(
        '/vendors/quick-add', json={'name': 'Subscription vendor'}
    )
    assert vendor_response.status_code == 201
    vendor_id = vendor_response.get_json()['id']
    form = _bank_form(
        account,
        category,
        end_date=(date.today() + relativedelta(months=2)).isoformat(),
    )
    form['vendor_id'] = str(vendor_id)
    response = client.post(
        '/transactions/subscriptions/create',
        data=form,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Stream service' in response.data
    assert Subscription.query.count() == 1
    assert Transaction.query.filter_by(is_paid=False).count() == 3
    subscription = Subscription.query.first()
    assert subscription.vendor_id == vendor_id
    assert all(
        transaction.vendor_id == vendor_id
        for transaction in Transaction.query.filter_by(
            subscription_id=subscription.id
        ).all()
    )
    response = client.get(f'/transactions/subscriptions/{subscription.id}/edit')
    assert response.status_code == 200
    assert b"openQuickAddVendor('vendor_id')" in response.data
    assert b'id="quickAddVendorModal"' in response.data
    assert b'js/quick_add_vendor.js' in response.data


def test_credit_card_subscription_removes_only_pending_entries(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    category = Category(
        family_id=family.id,
        name='Streaming',
        head_budget='Entertainment',
        sub_budget='Streaming',
        category_type='expense',
    )
    card = CreditCard(
        family_id=family.id,
        card_name='Household Card',
        annual_apr=Decimal('24.00'),
        monthly_apr=Decimal('2.00'),
        credit_limit=Decimal('5000.00'),
        current_balance=Decimal('0.00'),
        is_active=True,
    )
    db.session.add_all([category, card])
    db.session.commit()

    subscription = SubscriptionService.create(MultiDict({
        'name': 'Stream service',
        'amount': '12.99',
        'target_type': 'credit_card',
        'account_id': '',
        'credit_card_id': str(card.id),
        'category_id': str(category.id),
        'vendor_id': '',
        'frequency': 'monthly',
        'start_date': date.today().isoformat(),
        'end_date': (date.today() + relativedelta(months=2)).isoformat(),
        'horizon_years': '1',
    }))
    db.session.flush()
    entries = CreditCardTransaction.query.filter_by(
        subscription_id=subscription.id
    ).order_by(CreditCardTransaction.date).all()
    assert len(entries) == 3
    assert all(entry.amount == Decimal('-12.99') for entry in entries)

    entries[0].is_paid = True
    db.session.flush()
    SubscriptionService.cancel(subscription.id)
    db.session.flush()
    assert CreditCardTransaction.query.filter_by(
        subscription_id=subscription.id, is_paid=False
    ).count() == 0
    assert CreditCardTransaction.query.filter_by(
        subscription_id=subscription.id, is_paid=True
    ).count() == 1
