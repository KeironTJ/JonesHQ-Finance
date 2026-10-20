from datetime import date, timedelta

import pytest

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard, CreditCardPromotion
from models.family import Family
from models.mortgage import MortgageProduct
from models.plans import Plan
from models.property import Property
from models.subscriptions import Subscription
from models.transactions import Transaction
from models.users import User
from services.analytics.attention_service import AttentionService
from tests.auth_helpers import login_client


TODAY = date(2026, 10, 20)


def _scope(monkeypatch, family, user):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    monkeypatch.setattr('services.platform.preference_service.get_current_user_id', lambda: user.id)
    monkeypatch.setattr(
        'services.analytics.attention_service.can_access_section', user.can_access_section,
    )


def _records(family_id, title, owner_id=None):
    account = Account(
        family_id=family_id, name=title, account_type='Current',
        is_active=True, owner_id=owner_id,
    )
    category = Category(family_id=family_id, name=title, category_type='expense')
    card = CreditCard(
        family_id=family_id, card_name=title, annual_apr=24, monthly_apr=2,
        credit_limit=1000, is_active=True, owner_id=owner_id,
        purchase_0_percent_until=TODAY + timedelta(days=10),
    )
    prop = Property(family_id=family_id, address=title, is_active=True)
    plan = Plan(
        family_id=family_id, title=title, status='active',
        target_date=TODAY, owner_id=owner_id,
    )
    db.session.add_all([account, category, card, prop, plan])
    db.session.flush()
    product = MortgageProduct(
        family_id=family_id, property_id=prop.id, lender=title, product_name='Fixed',
        start_date=TODAY - timedelta(days=365), end_date=TODAY + timedelta(days=10),
        term_months=24, initial_balance=100000, current_balance=90000,
        annual_rate=4, monthly_payment=500, is_current=True, is_active=True,
    )
    transaction = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        description=title, amount=-10, is_paid=False,
        transaction_date=TODAY - timedelta(days=1),
    )
    promotion = CreditCardPromotion(
        family_id=family_id, credit_card_id=card.id, promotion_type='purchase',
        apr_rate=0, start_date=TODAY - timedelta(days=10),
        end_date=card.purchase_0_percent_until,
    )
    db.session.add_all([product, transaction, promotion])
    db.session.commit()
    return account, card, product, plan, transaction, promotion


def test_attention_covers_all_sources_deduplicates_promotions_and_sorts(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    account, card, product, plan, transaction, _ = _records(family.id, 'Visible')
    result = AttentionService.get_data(TODAY)
    assert result['window_days'] == 60
    items = result['items']
    assert [item['kind'] for item in items] == ['transaction', 'plan', 'credit_card', 'mortgage']
    assert [item['days_remaining'] for item in items] == [-1, 0, 10, 10]
    assert items[0]['params'] == {'id': transaction.id}
    assert items[1]['params'] == {'plan_id': plan.id}
    assert items[2]['params'] == {'id': card.id}
    assert items[3]['params'] == {'property_id': product.property_id}


def test_attention_uses_inclusive_personal_horizon_and_keeps_overdue_plans(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    user.preferences = {'dashboard.attention_days': 14}
    db.session.add_all([
        Plan(family_id=family.id, title=title, status=status, target_date=due)
        for title, status, due in [
            ('Past', 'active', TODAY - timedelta(days=100)),
            ('Today', 'active', TODAY),
            ('Boundary', 'active', TODAY + timedelta(days=14)),
            ('Outside', 'active', TODAY + timedelta(days=15)),
            ('Completed', 'completed', TODAY),
            ('Archived', 'archived', TODAY),
            ('Draft', 'draft', TODAY),
            ('Undated', 'active', None),
        ]
    ])
    db.session.commit()
    result = AttentionService.get_data(TODAY)
    assert result['window_days'] == 14
    assert [item['title'] for item in result['items']] == ['Past', 'Today', 'Boundary']


def test_attention_hides_other_families_and_private_records(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    other = Family(name='Other family')
    member = User(
        family_id=family.id, email='private@example.com', name='Private', role='member',
        password_hash='unused',
    )
    db.session.add_all([other, member])
    db.session.commit()
    _records(other.id, 'Foreign secret')
    _records(family.id, 'Private secret', owner_id=member.id)
    _records(family.id, 'Own private', owner_id=user.id)
    titles = [item['title'] for item in AttentionService.get_data(TODAY)['items']]
    assert 'Foreign secret' not in titles
    assert 'Foreign secret: Fixed' not in titles
    assert 'Private secret' not in titles
    assert 'Private secret: Fixed' in titles
    assert titles.count('Own private') == 3


def test_attention_excludes_inaccessible_sections(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    _records(family.id, 'Restricted')
    user.role = 'member'
    user.set_allowed_sections(['plans'])
    db.session.commit()
    assert [item['kind'] for item in AttentionService.get_data(TODAY)['items']] == ['plan']
    user.set_allowed_sections([])
    db.session.commit()
    assert AttentionService.get_data(TODAY)['items'] == []


def test_attention_includes_next_active_subscription_charge(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    account, _, _, _, _, _ = _records(family.id, 'Subscription target')
    subscription = Subscription(
        family_id=family.id,
        name='Streaming',
        amount=-12.99,
        frequency='monthly',
        start_date=TODAY + timedelta(days=10),
        horizon_years=1,
        account_id=account.id,
        is_active=True,
    )
    db.session.add(subscription)
    db.session.commit()

    result = AttentionService.get_data(TODAY)
    item = next(item for item in result['items'] if item['kind'] == 'subscription')
    assert item['title'] == 'Streaming'
    assert item['due_date'] == TODAY + timedelta(days=10)
    assert item['endpoint'] == 'transactions.edit_subscription'
    assert item['params'] == {'id': subscription.id}
    assert item['context'] == 'Subscription target / £12.99'

    subscription.is_active = False
    db.session.commit()
    assert not any(
        item['kind'] == 'subscription'
        for item in AttentionService.get_data(TODAY)['items']
    )


@pytest.mark.parametrize('change', ['paid', 'today', 'future', 'inactive_account'])
def test_attention_only_flags_past_pending_entries_on_active_accounts(
    app, family, user, monkeypatch, change,
):
    _scope(monkeypatch, family, user)
    account, _, _, _, transaction, _ = _records(family.id, 'Entry')
    if change == 'paid':
        transaction.is_paid = True
    elif change == 'today':
        transaction.transaction_date = TODAY
    elif change == 'future':
        transaction.transaction_date = TODAY + timedelta(days=1)
    else:
        account.is_active = False
    db.session.commit()
    assert not any(item['kind'] == 'transaction' for item in AttentionService.get_data(TODAY)['items'])


def test_attention_excludes_inactive_and_out_of_window_products(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    _, card, product, _, _, promotion = _records(family.id, 'Products')
    card.purchase_0_percent_until = TODAY - timedelta(days=1)
    promotion.end_date = TODAY - timedelta(days=1)
    product.is_current = False
    db.session.commit()
    assert {item['kind'] for item in AttentionService.get_data(TODAY)['items']} == {'plan', 'transaction'}
    card.purchase_0_percent_until = TODAY + timedelta(days=61)
    product.is_current = True
    product.end_date = TODAY + timedelta(days=61)
    db.session.commit()
    assert {item['kind'] for item in AttentionService.get_data(TODAY)['items']} == {'plan', 'transaction'}
    card.purchase_0_percent_until = TODAY
    product.end_date = TODAY
    card.is_active = False
    product.is_active = False
    db.session.commit()
    assert {item['kind'] for item in AttentionService.get_data(TODAY)['items']} == {'plan', 'transaction'}


def test_attention_includes_exact_expiry_boundary_and_overdue_current_mortgage(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    _, card, product, _, _, promotion = _records(family.id, 'Boundary')
    card.purchase_0_percent_until = TODAY + timedelta(days=60)
    card.balance_transfer_0_percent_until = TODAY
    promotion.end_date = card.purchase_0_percent_until
    product.end_date = TODAY - timedelta(days=100)
    db.session.commit()
    items = AttentionService.get_data(TODAY)['items']
    assert len([item for item in items if item['kind'] == 'credit_card']) == 2
    assert next(item for item in items if item['kind'] == 'mortgage')['days_remaining'] == -100


def test_dashboard_renders_attention_and_action_links(app, family, user):
    plan = Plan(family_id=family.id, title='<Review plan>', target_date=date.today())
    db.session.add(plan)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Needs attention' in html
    assert '&lt;Review plan&gt;' in html
    assert f'href="/plans/{plan.id}"' in html
    assert 'Reminder window: 60 days' in html


def test_dashboard_empty_attention_state(app, family, user):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/')
    assert response.status_code == 200
    assert b'No items need attention in your accessible sections' in response.data


def test_attention_tiles_keep_explanation_and_snooze_controls_on_demand(app, family, user):
    from html.parser import HTMLParser

    class DetailParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.details = []

        def handle_starttag(self, tag, attrs):
            if tag == 'details':
                self.details.append(dict(attrs))

    plan = Plan(
        family_id=family.id, title='A long family plan title for smaller screens',
        target_date=date.today(),
    )
    db.session.add(plan)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/?attention_kind=plan').get_data(as_text=True)
    parser = DetailParser()
    parser.feed(html)
    row_details = [
        attrs for attrs in parser.details
        if 'attention-detail' in attrs.get('class', '')
        or 'attention-snooze-options' in attrs.get('class', '')
    ]
    assert len(row_details) == 2
    assert all('open' not in attrs for attrs in row_details)
    assert f'<time datetime="{date.today().isoformat()}">' in html
    assert 'attention-status is-today' in html
    assert 'Details<span class="visually-hidden"> for A long family plan' in html
    assert 'Review this active plan and its target date.' in html
    assert 'name="days"' in html
    assert 'aria-label="Snooze reminder for A long family plan' in html


@pytest.mark.parametrize('query, expanded', [
    ('', False),
    ('?year=2025', False),
    ('?attention_kind=plan', True),
    ('?attention_timing=past', True),
    ('?attention_view=snoozed', True),
    ('?attention_page=2', True),
])
def test_attention_starts_collapsed_but_stays_open_during_queue_navigation(
    app, family, user, query, expanded,
):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(f'/{query}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    expected_class = 'collapse show' if expanded else 'collapse'
    assert f'id="attentionCollapse" class="{expected_class}"' in html
    assert (
        f'aria-expanded="{str(expanded).lower()}" aria-controls="attentionCollapse"'
        in html
    )
    assert 'type="button" data-bs-toggle="collapse" data-bs-target="#attentionCollapse"' in html
    card = html.split('id="needs-attention"', 1)[1].split('</section>', 1)[0]
    summary, content = card.split('<div id="attentionCollapse"', 1)
    assert 'class="card-header bg-primary text-white p-0"' in summary
    assert '<h2 class="h5 mb-0 w-100" id="attentionHeading">' in summary
    assert '<button class="attention-toggle w-100' in summary
    assert 'Needs attention' in summary
    assert 'badge bg-light text-dark' in summary
    assert 'Click to review' not in summary
    assert '</button>' in summary
    assert 'attention-toolbar' in content
    assert '.attention-toggle:hover' not in html
    assert '.attention-toggle.collapsed .dashboard-chevron { transform: rotate(-90deg); }' in html
    assert 'background: var(--bg-surface-3);' in html


def test_attention_queue_paginates_filters_and_clamps_after_removal(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    _records(family.id, 'Mixed')
    db.session.add_all([
        Plan(family_id=family.id, title=f'Plan {index:02}', target_date=TODAY + timedelta(days=index))
        for index in range(23)
    ])
    db.session.commit()
    first = AttentionService.get_queue({}, TODAY)
    second = AttentionService.get_queue({'attention_page': '2'}, TODAY)
    assert first['total'] == 27
    assert first['pages'] == 3
    assert len(first['items']) == len(second['items']) == 10
    assert {item['key'] for item in first['items']}.isdisjoint(
        {item['key'] for item in second['items']},
    )
    assert first['counts'] == {
        'transaction': 1,
        'plan': 24,
        'credit_card': 1,
        'mortgage': 1,
        'subscription': 0,
    }
    past = AttentionService.get_queue({'attention_timing': 'past'}, TODAY)
    assert [item['kind'] for item in past['items']] == ['transaction']
    today = AttentionService.get_queue({'attention_timing': 'today', 'attention_kind': 'plan'}, TODAY)
    assert len(today['items']) == 2
    upcoming = AttentionService.get_queue({'attention_timing': 'upcoming'}, TODAY)
    assert all(item['days_remaining'] > 0 for item in upcoming['items'])
    last = AttentionService.get_queue({'attention_page': '999'}, TODAY)
    assert last['page'] == 3
    assert (last['start'], last['end']) == (21, 27)


@pytest.mark.parametrize('data', [
    {'attention_kind': 'invalid'}, {'attention_timing': 'invalid'},
    {'attention_view': 'invalid'}, {'attention_page': 'bad'}, {'attention_page': '0'},
])
def test_attention_queue_rejects_invalid_filters(app, family, user, monkeypatch, data):
    _scope(monkeypatch, family, user)
    with pytest.raises(ValueError):
        AttentionService.get_queue(data, TODAY)


@pytest.mark.parametrize('duration', ['1', '7', '30'])
def test_snooze_is_personal_persistent_and_expires_on_the_return_date(
    app, family, user, monkeypatch, duration,
):
    _scope(monkeypatch, family, user)
    _, _, _, plan, _, _ = _records(family.id, 'Reminder')
    key = next(item['key'] for item in AttentionService.get_data(TODAY)['items'] if item['kind'] == 'plan')
    preferences = {'dashboard.attention_days': 60, 'dashboard.networth_expanded': False}
    user.preferences = preferences
    db.session.commit()
    AttentionService.snooze({'key': key, 'days': duration}, TODAY)
    db.session.expire(user)
    stored = user.preferences['dashboard.attention_snoozes']
    assert stored[key] == (TODAY + timedelta(days=int(duration))).isoformat()
    assert user.preferences['dashboard.networth_expanded'] is False
    assert plan.status == 'active'
    active = AttentionService.get_queue({}, TODAY)
    assert active['active_count'] == 3
    assert active['snoozed_count'] == 1
    assert key not in [item['key'] for item in active['items']]
    snoozed = AttentionService.get_queue({'attention_view': 'snoozed'}, TODAY)
    assert [item['key'] for item in snoozed['items']] == [key]
    returned = AttentionService.get_queue({}, TODAY + timedelta(days=int(duration)))
    assert key in [item['key'] for item in returned['items']]
    member = User(
        family_id=family.id, name='Member', email='queue-member@example.com',
        password_hash='unused', role='admin',
    )
    db.session.add(member)
    db.session.commit()
    _scope(monkeypatch, family, member)
    assert key in [item['key'] for item in AttentionService.get_queue({}, TODAY)['items']]
    assert not member.preferences


def test_restore_and_changed_dates_do_not_suppress_fresh_reminders(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    _, _, _, plan, _, _ = _records(family.id, 'Reminder')
    key = next(item['key'] for item in AttentionService.get_data(TODAY)['items'] if item['kind'] == 'plan')
    AttentionService.snooze({'key': key, 'days': '7'}, TODAY)
    AttentionService.snooze({'key': key, 'days': '0'}, TODAY)
    assert key in [item['key'] for item in AttentionService.get_queue({}, TODAY)['items']]
    AttentionService.snooze({'key': key, 'days': '7'}, TODAY)
    plan.target_date = TODAY + timedelta(days=1)
    db.session.commit()
    queue = AttentionService.get_queue({}, TODAY)
    assert any(item['kind'] == 'plan' and item['key'] != key for item in queue['items'])
    with pytest.raises(ValueError, match='no longer available'):
        AttentionService.snooze({'key': key, 'days': '30'}, TODAY)


@pytest.mark.parametrize('duration', ['', '2', '-1', '366', None])
def test_snooze_rejects_invalid_duration(app, family, user, monkeypatch, duration):
    _scope(monkeypatch, family, user)
    with pytest.raises(ValueError, match='Choose 1, 7 or 30'):
        AttentionService.snooze({'key': 'anything', 'days': duration}, TODAY)
    assert not user.preferences


def test_snooze_cannot_target_foreign_private_or_forbidden_reminders(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    _records(family.id, 'Reminder')
    keys = [item['key'] for item in AttentionService.get_data(TODAY)['items']]
    user.role = 'member'
    user.set_allowed_sections([])
    db.session.commit()
    for key in keys:
        with pytest.raises(ValueError, match='no longer available'):
            AttentionService.snooze({'key': key, 'days': '7'}, TODAY)
    other = Family(name='Other')
    db.session.add(other)
    db.session.commit()
    _, _, _, plan, _, _ = _records(other.id, 'Foreign')
    with pytest.raises(ValueError, match='no longer available'):
        AttentionService.snooze({'key': f'plan:{plan.id}:{TODAY.isoformat()}', 'days': '7'}, TODAY)
    assert not user.preferences


def test_snooze_route_preserves_filters_and_handles_database_failure(app, family, user, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    plan = Plan(family_id=family.id, title='Route reminder', target_date=date.today())
    db.session.add(plan)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    key = f'plan:{plan.id}:{date.today().isoformat()}'
    data = {
        'key': key, 'days': '7', 'attention_kind': 'plan',
        'attention_page': '2', 'year': '2025',
    }
    response = client.post('/dashboard/attention/snooze', data=data)
    assert response.status_code == 302
    assert 'attention_kind=plan' in response.location
    assert 'year=2025' in response.location
    assert response.location.endswith('#needs-attention')
    snoozed = client.get('/?attention_view=snoozed').get_data(as_text=True)
    assert 'Restore reminder for Route reminder' in snoozed
    response = client.post('/dashboard/attention/snooze', data={'key': key, 'days': '0'})
    assert response.status_code == 302
    assert user.preferences['dashboard.attention_snoozes'] == {}

    def fail_commit():
        raise SQLAlchemyError('Test failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)
    response = client.post('/dashboard/attention/snooze', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Unable to update your reminder. Please try again.' in response.data
    assert user.preferences['dashboard.attention_snoozes'] == {}


def test_dashboard_limits_rendered_reminders_and_filters_without_javascript(app, family, user):
    db.session.add_all([
        Plan(family_id=family.id, title=f'Queue plan {index}', target_date=date.today())
        for index in range(25)
    ])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/').get_data(as_text=True)
    assert html.count('class="attention-item border-top"') == 10
    assert 'of 25 active reminders' in html
    assert 'Page 1 of 3' in html
    assert 'Reminder categories' in html
    assert 'Snooze duration for' in html
    empty = client.get('/?attention_kind=transaction').get_data(as_text=True)
    assert 'No reminders match this view.' in empty
    assert 'Clear filters' in empty
    invalid = client.get('/?attention_page=bad', follow_redirects=True)
    assert b'Choose a valid reminder page.' in invalid.data


def test_snooze_rejects_private_reminders_and_removes_expired_preferences(
    app, family, user, monkeypatch,
):
    _scope(monkeypatch, family, user)
    _, _, _, plan, _, _ = _records(family.id, 'Reminder')
    key = next(item['key'] for item in AttentionService.get_data(TODAY)['items'] if item['kind'] == 'plan')
    member = User(
        family_id=family.id, name='Private', email='snooze-private@example.com',
        password_hash='unused', role='member',
    )
    db.session.add(member)
    db.session.flush()
    plan.owner_id = member.id
    db.session.commit()
    with pytest.raises(ValueError, match='no longer available'):
        AttentionService.snooze({'key': key, 'days': '7'}, TODAY)
    assert not user.preferences
    plan.owner_id = user.id
    user.preferences = {
        'dashboard.attention_snoozes': {
            'expired': (TODAY - timedelta(days=1)).isoformat(),
            'returns-today': TODAY.isoformat(),
        },
    }
    db.session.commit()
    AttentionService.snooze({'key': key, 'days': '1'}, TODAY)
    assert user.preferences['dashboard.attention_snoozes'] == {
        key: (TODAY + timedelta(days=1)).isoformat(),
    }


def test_queue_clamps_page_when_last_item_is_snoozed(app, family, user, monkeypatch):
    _scope(monkeypatch, family, user)
    db.session.add_all([
        Plan(family_id=family.id, title=f'Plan {index}', target_date=TODAY)
        for index in range(11)
    ])
    db.session.commit()
    last = AttentionService.get_queue({'attention_page': '2'}, TODAY)
    assert len(last['items']) == 1
    AttentionService.snooze({'key': last['items'][0]['key'], 'days': '7'}, TODAY)
    clamped = AttentionService.get_queue({'attention_page': '2'}, TODAY)
    assert (clamped['page'], clamped['pages'], clamped['total']) == (1, 1, 10)
    assert len(clamped['items']) == 10


def test_snooze_post_requires_login_and_csrf(app, family, user, monkeypatch):
    from flask import g

    g.pop('_login_user', None)
    client = app.test_client()
    response = client.post('/dashboard/attention/snooze', data={'key': 'anything', 'days': '7'})
    assert response.status_code == 302
    assert response.location.startswith('/intro?next=')
    login_client(client, user.id)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    assert client.post('/dashboard/attention/snooze', data={
        'key': 'anything', 'days': '7',
    }).status_code == 400
    assert not user.preferences
