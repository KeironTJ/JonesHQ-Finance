import pytest
from flask import g
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.accounts import Account
from services.finance.preference_service import FinancePreferenceService
from tests.auth_helpers import detach_user_from_households, login_client
from tests.test_workspace_ui import NavigationParser


def test_central_preferences_do_not_load_finance_data(app, user, monkeypatch):
    def unexpected_finance_query():
        pytest.fail('Central preferences must not load Finance page data.')

    monkeypatch.setattr(FinancePreferenceService, 'get_page_data', unexpected_finance_query)
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/preferences')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="appearanceForm"' in html
    assert 'name="default_account_id"' not in html
    assert 'name="dashboard.attention_days"' not in html
    assert 'href="/preferences/finance"' in html


@pytest.mark.parametrize('role', ['admin', 'member'])
def test_finance_preferences_use_finance_navigation_for_owners_and_members(app, user, role):
    user.role = role
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/preferences/finance')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'action="/preferences/finance"' in html
    assert 'id="appearanceForm"' not in html
    assert 'name="dashboard.attention_days"' in html
    parser = NavigationParser()
    parser.feed(html)
    assert [link['href'] for link in parser.links if link.get('aria-current') == 'page'] == ['/hub/settings/finance']
    assert sum(link['href'] == '/hub/settings/finance' for link in parser.links) == 1
    assert ('href="/settings/access"' in html) == (role == 'admin')


@pytest.mark.parametrize('path', ['/preferences', '/preferences/finance'])
def test_finance_preference_posts_preserve_appearance_and_personal_scope(app, family, user, path):
    account = Account(family_id=family.id, name='Current', account_type='Current', is_active=True)
    db.session.add(account)
    user.preferences = {'appearance.mode': 'auto', 'appearance.palette': 'purple'}
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.post(path, data={
        'default_account_id': str(account.id),
        'dashboard.attention_days': '90',
        'dashboard.networth_expanded': '1',
    })
    assert response.status_code == 302
    assert response.location.endswith('/preferences/finance')
    assert user.default_account_id == account.id
    assert user.preferences['appearance.mode'] == 'auto'
    assert user.preferences['appearance.palette'] == 'purple'
    assert user.preferences['dashboard.attention_days'] == 90
    for destination in ('/hub', '/preferences', '/preferences/finance', '/dashboard'):
        html = client.get(destination).get_data(as_text=True)
        assert 'data-mode="auto" data-palette="purple"' in html


def test_finance_preferences_validate_and_report_write_failures(app, user, monkeypatch):
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/preferences/finance', data={'dashboard.attention_days': '366'})
    assert response.status_code == 200
    assert b'value="366" aria-describedby="attentionDaysHelp"' in response.data
    assert not user.preferences

    def fail_commit():
        raise SQLAlchemyError('Test failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)
    response = client.post('/preferences/finance', data={'dashboard.attention_days': '90'})
    assert response.status_code == 200
    assert b'Unable to save your preferences. Please try again.' in response.data
    assert not user.preferences


def test_detached_account_can_edit_appearance_but_not_finance_defaults(app, user):
    detach_user_from_households(user)
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/preferences').get_data(as_text=True)
    assert 'id="appearanceForm"' in html
    assert 'href="/preferences/finance"' not in html
    assert client.get('/preferences/finance').location.endswith('/preferences')
    assert client.post('/preferences/finance', data={}).location.endswith('/preferences')
    assert not user.preferences


def test_finance_preferences_require_login(app):
    g.pop('_login_user', None)
    client = app.test_client()
    assert client.get('/preferences/finance').status_code == 302
    assert client.post('/preferences/finance', data={}).status_code == 302
