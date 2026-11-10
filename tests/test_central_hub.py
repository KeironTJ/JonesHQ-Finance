import pytest
from flask import g

from extensions import db
from tests.auth_helpers import detach_user_from_households, login_client
from tests.test_workspace_ui import NavigationParser


def test_public_root_remains_public_and_hub_requires_login(app):
    g.pop('_login_user', None)
    client = app.test_client()
    assert client.get('/').location.endswith('/intro')
    response = client.get('/central/')
    assert response.status_code == 302
    assert 'next=' in response.location


def test_root_opens_hub_and_finance_remains_separate(app, user):
    client = app.test_client()
    login_client(client, user.id)
    assert client.get('/').location.endswith('/central/')
    hub = client.get('/central/')
    assert hub.status_code == 200
    html = hub.get_data(as_text=True)
    assert 'Open Finance' in html
    assert 'Open Household Hub' in html
    assert 'href="/finance/dashboard"' in html
    assert 'href="/finance/transactions"' not in html
    finance = client.get('/finance/dashboard').get_data(as_text=True)
    assert 'Your finances, in focus.' in finance
    assert 'href="/central/"' in finance
    assert 'href="/finance/transactions"' in finance


@pytest.mark.parametrize('path', ['/central/', '/central/preferences', '/central/account/security', '/central/family/'])
def test_shared_pages_have_central_navigation(app, user, path):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(path)
    assert response.status_code == 200
    parser = NavigationParser()
    parser.feed(response.get_data(as_text=True))
    hrefs = {link['href'] for link in parser.links}
    assert {'/central/', '/finance/dashboard', '/central/settings'} <= hrefs
    assert not {'/central/account/security', '/central/preferences', '/central/family/'} & hrefs
    assert '/finance/transactions' not in hrefs
    assert '/finance/settings' not in hrefs


def test_member_can_enter_hub_without_receiving_finance_section_permissions(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    assert client.get('/central/').status_code == 200
    assert client.get('/finance/accounts').status_code == 200
    assert client.get('/finance/income').status_code == 403
    assert client.get('/central/family/').status_code == 403


def test_detached_account_hub_has_no_finance_entry(app, user):
    detach_user_from_households(user)
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/central/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'Household required' in html
    assert 'href="/finance/dashboard"' not in html
    assert 'href="/central/family/"' not in html


def test_password_login_defaults_to_hub_and_preserves_finance_deep_link(app, user):
    g.pop('_login_user', None)
    client = app.test_client()
    response = client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})
    assert response.location.endswith('/central/')
    client.post('/logout')
    g.pop('_login_user', None)
    response = client.post(
        '/login?next=/finance/dashboard?year=2027',
        data={'email': user.email, 'password': 'TestPass1!'},
    )
    assert response.location == '/finance/dashboard?year=2027'
