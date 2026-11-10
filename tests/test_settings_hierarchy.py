from html.parser import HTMLParser

import pytest
from flask import g

from extensions import db
from tests.auth_helpers import detach_user_from_households, login_client
from tests.test_workspace_ui import NavigationParser


class SettingsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and 'data-nav-search' in attrs:
            self.links.append(attrs['href'])


@pytest.mark.parametrize('path, area, page', [
    ('/hub/settings', 'Central', None),
    ('/hub/settings/finance', 'Finance', None),
    ('/settings', 'Finance', None),
    ('/preferences', 'Central', 'Appearance &amp; starting point'),
    ('/account/security', 'Central', 'Account &amp; security'),
    ('/account/security/two-factor/setup', 'Central', 'Account &amp; security'),
    ('/account/security/delete', 'Central', 'Account &amp; security'),
    ('/family/', 'Central', 'Household &amp; members'),
    ('/preferences/finance', 'Finance', 'Your preferences'),
    ('/settings/access', 'Finance', 'Access &amp; assignment'),
    ('/settings/modules/household', 'Finance', 'Payday &amp; budget periods'),
    ('/settings/modules/credit-cards', 'Finance', 'Credit cards'),
    ('/settings/modules/expenses', 'Finance', 'Work expenses'),
    ('/settings/modules/networth', 'Finance', 'Net worth'),
    ('/settings/tax', 'Finance', 'Tax &amp; National Insurance'),
    ('/vendors/types', 'Finance', 'Vendor types'),
])
def test_settings_editors_share_workspace_and_sub_navigation(app, user, path, area, page):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'aria-label="Settings breadcrumb"' in html
    if page:
        assert f'aria-label="{area} sub-settings"' in html
        assert f'aria-current="page">{page}</li>' in html
    sidebar = NavigationParser()
    sidebar.feed(html)
    expected = '/hub/settings' if area == 'Central' else '/hub/settings/finance'
    assert [link['href'] for link in sidebar.links if link.get('aria-current') == 'page'] == [expected]
    assert not {'/preferences', '/preferences/finance', '/settings', '/settings/access', '/family/'} & {
        link['href'] for link in sidebar.links
    }


def test_owner_settings_landing_pages_group_existing_editors(app, user):
    client = app.test_client()
    login_client(client, user.id)
    central = client.get('/hub/settings').get_data(as_text=True)
    finance = client.get('/hub/settings/finance').get_data(as_text=True)
    for path in ('/preferences', '/account/security', '/family/'):
        assert f'href="{path}"' in central
    for path in ('/preferences/finance', '/settings/access', '/settings/tax', '/vendors/types'):
        assert f'href="{path}"' in finance
    assert 'Only affects you' in finance
    assert 'Affects your household &middot; Owner only' in finance
    assert 'Coming soon' not in finance


def test_member_can_discover_preferences_but_not_owner_settings(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    for path in ('/hub/settings', '/hub/settings/finance', '/preferences/finance'):
        response = client.get(path)
        assert response.status_code == 200
        parser = SettingsParser()
        parser.feed(response.get_data(as_text=True))
        assert {'/preferences', '/account/security', '/preferences/finance'} <= set(parser.links)
        assert not any(link.startswith(('/settings', '/family/', '/vendors/types')) for link in parser.links)
    assert client.get('/settings').status_code == 403
    assert client.get('/settings/access').status_code == 403
    assert client.get('/family/').status_code == 403


def test_vendor_type_discovery_preserves_existing_member_permission(app, user):
    user.role = 'member'
    user.allowed_sections = '["vendors"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    assert client.get('/vendors/types').status_code == 200
    html = client.get('/hub/settings/finance').get_data(as_text=True)
    assert 'href="/vendors/types"' in html
    assert 'href="/settings/access"' not in html


def test_detached_account_settings_do_not_offer_household_editors(app, user):
    detach_user_from_households(user)
    client = app.test_client()
    login_client(client, user.id)
    for path in ('/hub/settings', '/hub/settings/finance'):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'href="/family/"' not in html
        assert 'href="/preferences/finance"' not in html
        assert 'href="/settings/access"' not in html
    assert 'Join a household before managing Finance settings.' in html


@pytest.mark.parametrize('path', ['/hub/settings', '/hub/settings/finance'])
def test_settings_landing_pages_require_login(app, path):
    g.pop('_login_user', None)
    response = app.test_client().get(path)
    assert response.status_code == 302
    assert 'next=' in response.location


def test_legacy_finance_preference_validation_keeps_finance_settings_context(app, user):
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/preferences', data={'dashboard.attention_days': '366'})
    assert response.status_code == 200
    assert 'aria-label="Finance sub-settings"' in response.get_data(as_text=True)
