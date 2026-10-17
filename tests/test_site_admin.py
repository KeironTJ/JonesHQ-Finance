from urllib.parse import urlsplit

import pytest
from flask import g

from extensions import db, limiter
from models.accounts import Account
from models.family import Family
from models.site_settings import SiteSettings
from models.users import SecurityEvent, User
from services.platform.auth_service import AuthService
from services.platform.household_invite_service import HouseholdInviteService
from services.platform.site_settings_service import SiteSettingsService
from tests.auth_helpers import login_client
from tests.test_account_security import enable_two_factor_admin, make_stale, request

PASSWORD = 'StrongPass1!'
SITE_ADMIN_PAGES = ('/site-admin/', '/site-admin/settings', '/site-admin/household-invites')


@pytest.fixture(autouse=True)
def reset_auth_state(app):
    g.pop('_login_user', None)
    limiter.reset()
    app.config['ALLOW_OPEN_REGISTRATION'] = False
    yield
    g.pop('_login_user', None)
    limiter.reset()


@pytest.fixture
def site_admin_client(app, user):
    enable_two_factor_admin(user)
    client = app.test_client()
    login_client(client, user.id)
    return client


def test_household_owner_without_site_admin_cannot_open_site_admin_area(app, user):
    client = app.test_client()
    login_client(client, user.id)

    for path in SITE_ADMIN_PAGES:
        assert request(client, 'get', path).status_code == 403, path
    assert request(client, 'post', '/site-admin/settings',
                   data={'household_signups_paused': 'y'}).status_code == 403
    assert SiteSettingsService.household_signups_paused() is False

    dashboard = request(client, 'get', '/')
    assert b'Site admin area' not in dashboard.data
    assert b'Owner' in dashboard.data


def test_anonymous_user_is_sent_to_sign_in(app):
    response = app.test_client().get('/site-admin/')
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path in ('/login', '/intro')


def test_site_admin_area_requires_recent_password(site_admin_client, user):
    make_stale(user)
    for path in SITE_ADMIN_PAGES:
        response = request(site_admin_client, 'get', path)
        assert response.status_code == 302, path
        assert urlsplit(response.headers['Location']).path == '/account/confirm', path


def test_overview_is_clearly_separate_and_has_no_household_financial_data(site_admin_client, user):
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    db.session.add(Account(family_id=other_family.id, name='ZZSECRET acct', account_type='Joint',
                           balance=1, is_active=True))
    db.session.commit()

    response = request(site_admin_client, 'get', '/site-admin/')

    assert response.status_code == 200
    assert b'site-admin-banner' in response.data
    assert b'Back to my household' in response.data
    assert b'ZZSECRET' not in response.data
    assert b'Invite only' in response.data
    assert b'test-only-secret-key' not in response.data
    assert b'Site admin area' in request(site_admin_client, 'get', '/').data


def test_legacy_admin_url_redirects_to_site_admin_area(site_admin_client):
    response = request(site_admin_client, 'get', '/admin')
    assert response.status_code in (301, 302, 308)
    assert urlsplit(response.headers['Location']).path.startswith('/site-admin')


def test_console_lives_under_site_admin(site_admin_client):
    response = request(site_admin_client, 'get', '/site-admin/console/')
    assert response.status_code == 200
    assert b'Site admin console' in response.data
    assert b'Back to my household' in response.data


def test_pausing_signups_blocks_registration_and_is_audited(site_admin_client, user, app):
    response = request(site_admin_client, 'post', '/site-admin/settings', data={
        'household_signups_paused': 'y',
        'signups_paused_message': 'Back next week.',
        'announcement': '',
        'announcement_level': 'info',
    })
    assert response.status_code == 302
    assert SiteSettingsService.household_signups_paused() is True
    event = SecurityEvent.query.filter_by(event_type='site_settings_updated').one()
    assert 'household_signups_paused' in event.details

    _, token = HouseholdInviteService.create_invite({})
    g.pop('_login_user', None)
    anonymous = app.test_client()
    page = anonymous.get(f'/register?invite={token}')
    assert b'Back next week.' in page.data
    assert b'name="password"' not in page.data

    anonymous.post('/register', data={
        'invite_token': token, 'household_name': 'New', 'name': 'New', 'email': 'new@example.com',
        'password': PASSWORD, 'confirm_password': PASSWORD,
    })
    assert User.query.filter_by(email='new@example.com').first() is None
    with pytest.raises(ValueError, match='Back next week'):
        AuthService.register_household({'invite_token': token, 'email': 'new@example.com'})


def test_announcement_is_shown_escaped_on_every_page(site_admin_client, app):
    request(site_admin_client, 'post', '/site-admin/settings', data={
        'announcement': 'Maintenance tonight <script>alert(1)</script>',
        'announcement_level': 'warning',
    })

    g.pop('_login_user', None)
    login_page = app.test_client().get('/login')
    assert b'Maintenance tonight &lt;script&gt;' in login_page.data
    assert b'<script>alert(1)</script>' not in login_page.data
    assert b'alert-warning' in login_page.data


def test_settings_service_validates_input(app):
    with pytest.raises(ValueError, match='announcement style'):
        SiteSettingsService.update({'announcement_level': 'purple'})
    with pytest.raises(ValueError, match='500 characters'):
        SiteSettingsService.update({'announcement': 'x' * 501})
    assert db.session.get(SiteSettings, 1) is None


def test_no_changes_records_no_event(app, monkeypatch):
    assert SiteSettingsService.update({}) == []
    assert SecurityEvent.query.filter_by(event_type='site_settings_updated').count() == 0
