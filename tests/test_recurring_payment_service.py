from tests.auth_helpers import login_client
from datetime import date
from decimal import Decimal
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from dateutil.relativedelta import relativedelta
from sqlalchemy import create_engine, inspect, text
from werkzeug.datastructures import MultiDict

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.recurring_payments import RecurringPayment, RecurringPaymentPriceChange
from models.transactions import Transaction
from models.users import User
from services.finance.recurring_payment_service import RecurringPaymentService
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


@pytest.fixture
def fixed_recurring_payment_today(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return date(2026, 1, 1)

    monkeypatch.setattr('services.finance.recurring_payment_service.date', FixedDate)
    return FixedDate.today()


@pytest.mark.parametrize('target_type', ['bank', 'credit_card'])
@pytest.mark.parametrize('policy, expected', [
    ('none', [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]),
    ('next', [date(2026, 2, 2), date(2026, 3, 2), date(2026, 3, 31)]),
    ('previous', [date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31)]),
])
def test_recurring_payment_adjusted_dates_and_metadata(
    app, family, monkeypatch, fixed_recurring_payment_today, target_type, policy, expected
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.recurring_payment_service.PaydayService.get_period_for_date',
        lambda value: value.strftime('%Y-%m'),
    )
    account, category = _add_bank_target(family)
    card = CreditCard(
        family_id=family.id, card_name='Card', annual_apr=Decimal('24'),
        monthly_apr=Decimal('2'), credit_limit=Decimal('5000'),
        current_balance=0, is_active=True,
    )
    db.session.add(card)
    db.session.commit()
    form = _bank_form(account, category, end_date='2026-03-31')
    for key, value in {
        'start_date': '2026-01-31', 'weekend_adjustment': policy,
        'target_type': target_type, 'credit_card_id': str(card.id),
    }.items():
        form[key] = value
    recurring_payment = RecurringPaymentService.create(form)
    db.session.commit()
    assert recurring_payment.weekend_adjustment == policy
    model = Transaction if target_type == 'bank' else CreditCardTransaction
    date_attr = 'transaction_date' if target_type == 'bank' else 'date'
    entries = model.query.filter_by(recurring_payment_id=recurring_payment.id).order_by(
        getattr(model, date_attr)
    ).all()
    assert [getattr(entry, date_attr) for entry in entries] == expected
    for entry, expected_date in zip(entries, expected):
        if target_type == 'bank':
            assert entry.year_month == expected_date.strftime('%Y-%m')
            assert entry.day_name == expected_date.strftime('%a')
            assert entry.payday_period == expected_date.strftime('%Y-%m')
        else:
            assert entry.month == expected_date.strftime('%Y-%m')
            assert entry.day_name == expected_date.strftime('%A')
    RecurringPaymentService.sync_pending(recurring_payment, today=fixed_recurring_payment_today)
    db.session.flush()
    assert model.query.filter_by(recurring_payment_id=recurring_payment.id).count() == 3
    preview = RecurringPaymentService.apply_price_change(recurring_payment.id, {
        'amount': '20', 'effective_date': '2026-02-01', 'note': 'Upgrade',
    }, today=fixed_recurring_payment_today)
    assert [change['date'] for change in preview['changes']] == [
        charge_date for charge_date in expected if charge_date >= date(2026, 2, 1)
    ]
    db.session.flush()
    for entry in entries:
        expected_amount = (
            Decimal('-20') if getattr(entry, date_attr) >= date(2026, 2, 1)
            else Decimal('-12.99')
        )
        assert entry.amount == expected_amount


@pytest.mark.parametrize('target_type', ['bank', 'credit_card'])
def test_changing_recurring_payment_policy_preserves_paid_fixed_occurrences(
    app, family, monkeypatch, fixed_recurring_payment_today, target_type
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)
    card = CreditCard(
        family_id=family.id, card_name='Card', annual_apr=Decimal('24'),
        monthly_apr=Decimal('2'), credit_limit=Decimal('5000'),
        current_balance=0, is_active=True,
    )
    db.session.add(card)
    db.session.commit()
    form = _bank_form(account, category, end_date='2026-05-31')
    for key, value in {
        'start_date': '2026-01-31', 'weekend_adjustment': 'previous',
        'target_type': target_type, 'credit_card_id': str(card.id),
    }.items():
        form[key] = value
    recurring_payment = RecurringPaymentService.create(form)
    db.session.flush()
    model = Transaction if target_type == 'bank' else CreditCardTransaction
    date_attr = 'transaction_date' if target_type == 'bank' else 'date'
    entries = model.query.filter_by(recurring_payment_id=recurring_payment.id).order_by(
        getattr(model, date_attr)
    ).all()
    entries[0].is_paid = True
    entries[1].is_fixed = True
    protected_ids = [entries[0].id, entries[1].id]
    db.session.commit()
    form['weekend_adjustment'] = 'next'
    RecurringPaymentService.update(recurring_payment.id, form)
    db.session.commit()
    for _ in range(2):
        RecurringPaymentService.sync_pending(recurring_payment, today=fixed_recurring_payment_today)
        db.session.flush()
    updated = model.query.filter_by(recurring_payment_id=recurring_payment.id).order_by(
        getattr(model, date_attr)
    ).all()
    assert [getattr(entry, date_attr) for entry in updated] == [
        date(2026, 1, 30), date(2026, 2, 27), date(2026, 3, 31),
        date(2026, 4, 30), date(2026, 6, 1),
    ]
    assert [updated[0].id, updated[1].id] == protected_ids
    assert updated[0].is_paid and updated[1].is_fixed
    preview = RecurringPaymentService.preview_price_change(recurring_payment.id, {
        'amount': '20', 'effective_date': '2026-01-31', 'note': 'Upgrade',
    }, today=fixed_recurring_payment_today)
    assert [change['date'] for change in preview['changes']] == [
        date(2026, 3, 31), date(2026, 4, 30), date(2026, 6, 1),
    ]
    assert preview['new_count'] == 0


@pytest.mark.parametrize('policy, today, expected', [
    ('next', date(2026, 12, 28), [date(2026, 12, 29)]),
    ('previous', date(2026, 12, 25), []),
    ('previous', date(2026, 12, 24), [date(2026, 12, 24)]),
    ('none', date(2026, 12, 25), [date(2026, 12, 25)]),
])
def test_recurring_payment_holiday_and_today_boundaries(app, policy, today, expected):
    recurring_payment = RecurringPayment(
        name='Holiday charge', amount=-10, frequency='monthly',
        start_date=date(2026, 12, 25), end_date=date(2026, 12, 25),
        horizon_years=1, weekend_adjustment=policy,
    )
    assert list(RecurringPaymentService._scheduled_dates(recurring_payment, today)) == expected


def test_recurring_payment_invalid_policy_preserves_form_selection(
    app, family, user, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)
    client = app.test_client()
    login_client(client, user.id)
    form = _bank_form(account, category)
    form['weekend_adjustment'] = 'invalid'
    response = client.post('/finance/transactions/recurring-payments/create', data=form)
    assert response.status_code == 200
    assert b'Select a valid weekend' in response.data
    assert RecurringPayment.query.count() == 0
    form['weekend_adjustment'] = 'next'
    form['name'] = ''
    response = client.post('/finance/transactions/recurring-payments/create', data=form)
    assert b'value="next" selected' in response.data


def test_recurring_payment_adjustment_migration_preserves_existing_rules(monkeypatch):
    migration = import_module(
        'migrations.versions.d8e2f4a6b0c9_add_subscription_weekend_adjustment'
    )
    engine = create_engine('sqlite://')
    try:
        with engine.begin() as connection:
            connection.execute(text(
                'CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, name TEXT NOT NULL)'
            ))
            connection.execute(text(
                "INSERT INTO subscriptions (id, name) VALUES (1, 'Existing rule')"
            ))
            monkeypatch.setattr(
                migration, 'op', Operations(MigrationContext.configure(connection))
            )
            migration.upgrade()
            assert connection.execute(text(
                'SELECT name, weekend_adjustment FROM subscriptions'
            )).one() == ('Existing rule', 'none')
            migration.downgrade()
            assert 'weekend_adjustment' not in {
                column['name'] for column in inspect(connection).get_columns('subscriptions')
            }
            assert connection.execute(text(
                'SELECT name FROM subscriptions'
            )).scalar_one() == 'Existing rule'
    finally:
        engine.dispose()


def test_recurring_payment_form_saves_and_restores_adjustment(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)
    client = app.test_client()
    login_client(client, user.id)
    form = _bank_form(account, category)
    form['weekend_adjustment'] = 'next'
    response = client.post('/finance/transactions/recurring-payments/create', data=form)
    assert response.status_code == 302
    recurring_payment = RecurringPayment.query.one()
    response = client.get(f'/finance/transactions/recurring-payments/{recurring_payment.id}/edit')
    assert b'value="next" selected' in response.data
    form['weekend_adjustment'] = 'previous'
    response = client.post(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/edit', data=form
    )
    assert response.status_code == 302
    assert recurring_payment.weekend_adjustment == 'previous'


def test_recurring_payment_updates_and_cancellation_leave_paid_bank_entries_untouched(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.recurring_payment_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    account, category = _add_bank_target(family)
    end_date = (date.today() + relativedelta(months=2)).isoformat()

    recurring_payment = RecurringPaymentService.create(
        _bank_form(account, category, end_date=end_date)
    )
    db.session.flush()
    entries = Transaction.query.filter_by(recurring_payment_id=recurring_payment.id).order_by(
        Transaction.transaction_date
    ).all()
    assert len(entries) == 3
    assert all(entry.amount == Decimal('-12.99') for entry in entries)

    paid_entry = entries[0]
    paid_entry.is_paid = True
    paid_amount = paid_entry.amount
    db.session.flush()

    updated_end_date = (date.today() + relativedelta(months=3)).isoformat()
    RecurringPaymentService.update(
        recurring_payment.id,
        _bank_form(
            account, category, amount='18.50', end_date=updated_end_date
        ),
    )
    db.session.flush()

    assert paid_entry.is_paid is True
    assert paid_entry.amount == paid_amount
    pending = Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=False
    ).all()
    assert len(pending) == 3
    assert all(entry.amount == Decimal('-12.99') for entry in pending)
    assert recurring_payment.amount == Decimal('-12.99')
    RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '18.50',
            'effective_date': date.today().isoformat(),
            'note': 'Upgrade',
        },
    )
    db.session.flush()
    assert all(entry.amount == Decimal('-18.50') for entry in pending)
    summary = RecurringPaymentService.get_summary(recurring_payment)
    assert summary['annual_cost'] == Decimal('222.00')
    assert summary['paid_count'] == 1
    assert summary['pending_count'] == 3
    assert summary['last_paid_amount'] == Decimal('12.99')
    assert summary['amount_changed'] is True

    RecurringPaymentService.set_active(recurring_payment.id, False)
    paused_end_date = (date.today() + relativedelta(months=4)).isoformat()
    RecurringPaymentService.update(
        recurring_payment.id,
        _bank_form(
            account, category, amount='21.00', end_date=paused_end_date
        ),
    )
    pending = Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=False
    ).all()
    assert len(pending) == 3
    assert all(entry.amount == Decimal('-18.50') for entry in pending)

    RecurringPaymentService.cancel(recurring_payment.id)
    db.session.flush()
    assert Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=False
    ).count() == 0
    assert Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=True
    ).count() == 1


def test_five_year_horizon_bounds_monthly_schedule(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)
    recurring_payment = RecurringPayment(
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
        RecurringPaymentService._scheduled_dates(recurring_payment, date.today())
    )
    horizon_end = date.today() + relativedelta(years=5)
    assert scheduled[0] == date.today()
    assert scheduled[-1] <= horizon_end
    assert len(scheduled) <= 61


def test_dated_price_change_previews_and_updates_only_future_unfixed_charges(
    app, family, monkeypatch,
):
    today = date.today()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.recurring_payment_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    account, category = _add_bank_target(family)
    recurring_payment = RecurringPaymentService.create(
        _bank_form(
            account,
            category,
            end_date=(today + relativedelta(months=4)).isoformat(),
        )
    )
    entries = Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id
    ).order_by(Transaction.transaction_date).all()
    assert len(entries) == 5
    entries[0].is_paid = True
    entries[3].is_fixed = True
    db.session.flush()

    first_change = MultiDict({
        'amount': '18.50',
        'effective_date': (today + relativedelta(months=2)).isoformat(),
        'note': 'Premium plan',
    })
    preview = RecurringPaymentService.preview_price_change(
        recurring_payment.id, first_change, today
    )
    assert [change['date'] for change in preview['changes']] == [
        today + relativedelta(months=2),
        today + relativedelta(months=4),
    ]
    assert preview['existing_count'] == 2
    assert preview['new_count'] == 0
    assert all(change['old_amount'] == Decimal('12.99') for change in preview['changes'])
    assert RecurringPaymentPriceChange.query.count() == 0
    with pytest.raises(ValueError, match='today or a future date'):
        RecurringPaymentService.preview_price_change(
            recurring_payment.id,
            {
                'amount': '18.50',
                'effective_date': (today - relativedelta(days=1)).isoformat(),
                'note': 'Scheduled increase',
            },
            today,
        )
    with pytest.raises(ValueError, match='reason for the price change'):
        RecurringPaymentService.preview_price_change(
            recurring_payment.id,
            {
                'amount': '18.50',
                'effective_date': today.isoformat(),
                'note': '  ',
            },
            today,
        )

    RecurringPaymentService.apply_price_change(recurring_payment.id, first_change, today)
    db.session.flush()
    assert entries[0].amount == Decimal('-12.99')
    assert entries[0].is_paid
    assert entries[1].amount == Decimal('-12.99')
    assert entries[2].amount == Decimal('-18.50')
    assert entries[3].amount == Decimal('-12.99')
    assert entries[3].is_fixed
    assert entries[4].amount == Decimal('-18.50')

    later_change = MultiDict({
        'amount': '20.00',
        'effective_date': (today + relativedelta(months=4)).isoformat(),
        'note': 'Annual increase',
    })
    RecurringPaymentService.apply_price_change(recurring_payment.id, later_change, today)
    db.session.flush()
    assert entries[2].amount == Decimal('-18.50')
    assert entries[4].amount == Decimal('-20.00')
    later_price = RecurringPaymentPriceChange.query.filter_by(
        effective_date=today + relativedelta(months=4)
    ).one()
    RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '21.00',
            'effective_date': (today + relativedelta(months=4)).isoformat(),
            'note': 'Corrected increase',
        },
        today,
        change_id=later_price.id,
    )
    db.session.flush()
    assert entries[2].amount == Decimal('-18.50')
    assert entries[4].amount == Decimal('-21.00')
    assert RecurringPaymentPriceChange.query.count() == 2
    assert later_price.note == 'Corrected increase'
    assert RecurringPaymentService._amount_for_date(
        recurring_payment, today + relativedelta(months=3)
    ) == Decimal('-18.50')
    with pytest.raises(ValueError, match='already scheduled'):
        RecurringPaymentService.preview_price_change(
            recurring_payment.id, later_change, today
        )


def test_moving_a_scheduled_price_change_previews_charges_that_revert(
    app, family, monkeypatch,
):
    today = date.today()
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.finance.recurring_payment_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    account, category = _add_bank_target(family)
    recurring_payment = RecurringPaymentService.create(
        _bank_form(
            account,
            category,
            end_date=(today + relativedelta(months=4)).isoformat(),
        )
    )
    price_change = RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '18.50',
            'effective_date': (today + relativedelta(months=1)).isoformat(),
            'note': 'Upgrade',
        },
        today,
    )['change']
    db.session.flush()

    preview = RecurringPaymentService.preview_price_change(
        recurring_payment.id,
        {
            'amount': '18.50',
            'effective_date': (today + relativedelta(months=3)).isoformat(),
            'note': 'Upgrade',
        },
        today,
        change_id=price_change.id,
    )
    assert [change['date'] for change in preview['changes']] == [
        today + relativedelta(months=1),
        today + relativedelta(months=2),
    ]
    assert all(change['old_amount'] == Decimal('18.50') for change in preview['changes'])
    assert all(change['new_amount'] == Decimal('12.99') for change in preview['changes'])

    RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '18.50',
            'effective_date': (today + relativedelta(months=3)).isoformat(),
            'note': 'Upgrade',
        },
        today,
        change_id=price_change.id,
    )
    db.session.flush()
    entries = Transaction.query.filter_by(
        recurring_payment_id=recurring_payment.id
    ).order_by(Transaction.transaction_date).all()
    assert [entry.amount for entry in entries] == [
        Decimal('-12.99'),
        Decimal('-12.99'),
        Decimal('-12.99'),
        Decimal('-18.50'),
        Decimal('-18.50'),
    ]


def test_recurring_payment_visibility_tracks_private_target_owner(
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
        'services.finance.recurring_payment_service.PaydayService.get_period_for_date',
        lambda txn_date: txn_date.strftime('%Y-%m'),
    )
    recurring_payment = RecurringPaymentService.create(_bank_form(account, category))
    db.session.flush()
    RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '15.99',
            'effective_date': date.today().isoformat(),
            'note': 'Price increase',
        },
    )
    db.session.flush()

    assert family_query(RecurringPayment).filter_by(id=recurring_payment.id).count() == 1
    assert family_query(RecurringPaymentPriceChange).filter_by(
        recurring_payment_id=recurring_payment.id
    ).count() == 1
    active_user_id['value'] = other_user.id
    assert family_query(RecurringPayment).filter_by(id=recurring_payment.id).count() == 0
    assert family_query(RecurringPaymentPriceChange).filter_by(
        recurring_payment_id=recurring_payment.id
    ).count() == 0

    account.owner_id = other_user.id
    db.session.flush()
    assert family_query(RecurringPayment).filter_by(id=recurring_payment.id).count() == 1
    assert family_query(RecurringPaymentPriceChange).filter_by(
        recurring_payment_id=recurring_payment.id
    ).count() == 1


def test_recurring_payment_templates_compile(app):
    app.jinja_env.get_template('transactions/recurring_payments.html')
    app.jinja_env.get_template('transactions/recurring_payment_form.html')
    app.jinja_env.get_template('transactions/recurring_payment_price_change.html')
    app.jinja_env.get_template('transactions/_recurring_payment_price_history.html')
    app.jinja_env.get_template('transactions/transactions.html')
    app.jinja_env.get_template('credit_cards/detail.html')


def test_recurring_payment_routes_create_and_list_rule(app, family, user):
    account, category = _add_bank_target(family)
    client = app.test_client()
    login_client(client, user.id)

    response = client.get('/finance/transactions/recurring-payments')
    assert response.status_code == 200
    response = client.get('/finance/transactions/recurring-payments/create')
    assert response.status_code == 200
    assert b"openQuickAddVendor('vendor_id')" in response.data
    assert b'id="quickAddVendorModal"' in response.data
    assert b'js/quick_add_vendor.js' in response.data
    vendor_response = client.post(
        '/finance/vendors/quick-add', json={'name': 'RecurringPayment vendor'}
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
        '/finance/transactions/recurring-payments/create',
        data=form,
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Stream service' in response.data
    assert RecurringPayment.query.count() == 1
    assert Transaction.query.filter_by(is_paid=False).count() == 3
    recurring_payment = RecurringPayment.query.first()
    assert recurring_payment.vendor_id == vendor_id
    assert all(
        transaction.vendor_id == vendor_id
        for transaction in Transaction.query.filter_by(
            recurring_payment_id=recurring_payment.id
        ).all()
    )
    response = client.get(f'/finance/transactions/recurring-payments/{recurring_payment.id}/edit')
    assert response.status_code == 200
    assert b'No dated price changes yet.' in response.data
    empty_change_response = client.get(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change'
    )
    assert b'No dated price changes yet.' in empty_change_response.data
    assert b'id="amount" type="number" class="form-control" readonly' in response.data
    assert b'Use Change price to schedule a dated price change' in response.data
    assert b"openQuickAddVendor('vendor_id')" in response.data
    assert b'id="quickAddVendorModal"' in response.data
    assert b'js/quick_add_vendor.js' in response.data
    price_change = MultiDict({
        'amount': '15.99',
        'effective_date': date.today().isoformat(),
        'note': 'Price increase',
    })
    response = client.post(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change',
        data=price_change,
    )
    assert response.status_code == 200
    assert b'Review forecast changes' in response.data
    assert b'Confirm price change' in response.data
    assert b'price-preview-mobile' in response.data
    assert b'<strong>Reason:</strong> Price increase' in response.data
    assert RecurringPaymentPriceChange.query.count() == 0
    altered_price_change = MultiDict(price_change)
    altered_price_change['amount'] = '25.00'
    altered_price_change['confirm_change'] = '1'
    response = client.post(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change',
        data=altered_price_change,
    )
    assert b'Review the price change preview before confirming' in response.data
    assert RecurringPaymentPriceChange.query.count() == 0
    price_change['confirm_change'] = '1'
    response = client.post(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change',
        data=price_change,
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Reason: Price increase' in response.data
    assert RecurringPaymentPriceChange.query.count() == 1
    edit_response = client.get(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/edit'
    )
    assert b'Price history' in edit_response.data
    assert b'<th scope="col">Reason</th>' in edit_response.data
    assert b'Price increase' in edit_response.data
    assert b'd-md-none' in edit_response.data
    assert b'Schedule a price change' in edit_response.data
    change_response = client.get(
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change'
    )
    assert b'<th scope="col">Reason</th>' in change_response.data
    assert b'Price increase' in change_response.data
    assert b'd-md-none' in change_response.data
    assert b'price-history-mobile' in change_response.data
    assert b'aria-label="Edit price change"' in change_response.data
    for history_response in (edit_response, change_response):
        assert b'css/recurring_payment_price_history.css' in history_response.data
    history_start = b'<section class="card recurring_payment-price-history"'
    edit_history = edit_response.data.split(history_start, 1)[1].split(b'</section>', 1)[0]
    change_history = change_response.data.split(history_start, 1)[1].split(b'</section>', 1)[0]
    assert edit_history == change_history
    recurring_payments_response = client.get('/finance/transactions/recurring-payments')
    assert b'd-xl-none' in recurring_payments_response.data
    assert b'recurring_payment-mobile-actions' in recurring_payments_response.data
    assert b'bi-currency-exchange' in recurring_payments_response.data
    assert b'aria-label="Edit recurring payment"' in recurring_payments_response.data
    assert b'aria-label="Pause recurring payment"' in recurring_payments_response.data
    assert b'aria-label="Cancel recurring payment"' in recurring_payments_response.data
    assert all(
        transaction.amount == Decimal('-15.99')
        for transaction in Transaction.query.filter_by(
            recurring_payment_id=recurring_payment.id
        ).all()
    )
    price_change_record = RecurringPaymentPriceChange.query.one()
    edit_path = (
        f'/finance/transactions/recurring-payments/{recurring_payment.id}/price-change/'
        f'{price_change_record.id}'
    )
    response = client.get(edit_path)
    assert response.status_code == 200
    assert b'value="15.99"' in response.data
    correction = MultiDict({
        'amount': '14.99',
        'effective_date': date.today().isoformat(),
        'note': 'Corrected price',
    })
    response = client.post(edit_path, data=correction)
    assert b'Review forecast changes' in response.data
    correction['confirm_change'] = '1'
    response = client.post(edit_path, data=correction, follow_redirects=True)
    assert response.status_code == 200
    assert RecurringPaymentPriceChange.query.count() == 1
    assert price_change_record.amount == Decimal('-14.99')
    assert price_change_record.note == 'Corrected price'


def test_recurring_payments_can_be_grouped_by_category(
    app, family, user, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account, category = _add_bank_target(family)

    for name, amount in (
        ('Streaming service', '12.00'),
        ('Music service', '5.00'),
    ):
        form = _bank_form(account, category, amount=amount)
        form['name'] = name
        RecurringPaymentService.create(form)
    card = CreditCard(
        family_id=family.id,
        card_name='Household Card',
        annual_apr=Decimal('24.00'),
        monthly_apr=Decimal('2.00'),
        credit_limit=Decimal('5000.00'),
        current_balance=Decimal('0.00'),
        is_active=True,
    )
    db.session.add(card)
    db.session.flush()
    RecurringPaymentService.create(MultiDict({
        'name': 'Uncategorised service',
        'amount': '3.00',
        'target_type': 'credit_card',
        'account_id': '',
        'credit_card_id': str(card.id),
        'category_id': '',
        'vendor_id': '',
        'frequency': 'monthly',
        'start_date': date.today().isoformat(),
        'end_date': '',
        'horizon_years': '1',
    }))
    db.session.commit()

    client = app.test_client()
    login_client(client, user.id)
    list_response = client.get('/finance/transactions/recurring-payments')
    assert list_response.status_code == 200
    assert b'By category' in list_response.data
    assert b'at current rates' not in list_response.data

    grouped_response = client.get(
        '/finance/transactions/recurring-payments?group_by=category'
    )
    assert grouped_response.status_code == 200
    assert b'Entertainment \xe2\x80\x94 Streaming' in grouped_response.data
    assert b'Uncategorized' in grouped_response.data
    assert grouped_response.data.count(b'2 payments') == 2
    assert grouped_response.data.count(b'\xc2\xa3204.00 / year at current rates') == 2
    assert grouped_response.data.count(b'1 payment') == 2
    assert grouped_response.data.count(b'\xc2\xa336.00 / year at current rates') == 2


def test_credit_card_recurring_payment_removes_only_pending_entries(
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

    recurring_payment = RecurringPaymentService.create(MultiDict({
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
        recurring_payment_id=recurring_payment.id
    ).order_by(CreditCardTransaction.date).all()
    assert len(entries) == 3
    assert all(entry.amount == Decimal('-12.99') for entry in entries)

    entries[0].is_paid = True
    db.session.flush()
    RecurringPaymentService.apply_price_change(
        recurring_payment.id,
        {
            'amount': '15.99',
            'effective_date': (
                date.today() + relativedelta(months=1)
            ).isoformat(),
            'note': 'Annual increase',
        },
    )
    db.session.flush()
    assert entries[0].amount == Decimal('-12.99')
    assert entries[1].amount == Decimal('-15.99')
    assert entries[2].amount == Decimal('-15.99')
    RecurringPaymentService.cancel(recurring_payment.id)
    db.session.flush()
    assert CreditCardTransaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=False
    ).count() == 0
    assert CreditCardTransaction.query.filter_by(
        recurring_payment_id=recurring_payment.id, is_paid=True
    ).count() == 1
