from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from flask import g

from extensions import db, limiter
from models.family import FamilyInvite
from models.users import SecurityEvent, User, UserSession
from services.platform.security_event_service import SecurityEventService
from services.platform.two_factor_service import TwoFactorService
from services.platform.user_session_service import UserSessionService, _now
from tests.auth_helpers import login_client


@pytest.fixture(autouse=True)
def reset_auth_state():
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


def request(client, method, path, **kwargs):
    # Tests share one app context, so force Flask-Login to reload the user each request.
    g.pop('_login_user', None)
    return getattr(client, method)(path, **kwargs)


def is_signed_in(client):
    return request(client, 'get', '/account/security').status_code == 200


def make_stale(user):
    UserSession.query.filter_by(user_id=user.id).update(
        {'reauthenticated_at': _now() - timedelta(hours=1)}, synchronize_session=False)
    db.session.commit()


def event_types(user):
    return [event.event_type for event in
            SecurityEvent.query.filter_by(user_id=user.id).order_by(SecurityEvent.id).all()]


def make_member(family, email='member@example.com'):
    member = User(email=email, name='Member', role='member', family_id=family.id)
    member.set_password('MemberPass1!')
    db.session.add(member)
    db.session.commit()
    return member


def change_password(client, current='TestPass1!', new='NewSecret#2024', confirm=None):
    return request(client, 'post', '/account/security/password', data={
        'current_password': current,
        'new_password': new,
        'confirm_password': new if confirm is None else confirm,
    })


def enable_two_factor_admin(user):
    user.is_site_admin = True
    db.session.commit()
    TwoFactorService.begin_setup(user)
    TwoFactorService.confirm_setup(user, {'code': pyotp.TOTP(user.totp_secret).now()})


# ── Change password ──────────────────────────────────────────────────────────

def test_change_password_signs_out_other_devices(app, user):
    client, other = app.test_client(), app.test_client()
    login_client(client, user.id)
    login_client(other, user.id)

    response = change_password(client)
    assert response.status_code == 302
    assert user.check_password('NewSecret#2024')
    assert is_signed_in(client)
    assert not is_signed_in(other)
    assert UserSession.query.filter_by(user_id=user.id, revoked_at=None).count() == 1
    assert 'password_changed' in event_types(user)


@pytest.mark.parametrize('kwargs, message', [
    ({'current': 'WrongPass1!'}, b'current password was not correct'),
    ({'confirm': 'Different#2024'}, b'do not match'),
    ({'new': 'TestPass1!'}, b'different from your current one'),
    ({'new': 'short'}, b'Password must'),
])
def test_change_password_rejections(app, user, kwargs, message):
    client = app.test_client()
    login_client(client, user.id)
    response = change_password(client, **kwargs)
    assert response.status_code == 302
    assert user.check_password('TestPass1!')
    page = request(client, 'get', '/account/security')
    assert message in page.data


def test_change_password_wrong_current_is_logged(app, user):
    client = app.test_client()
    login_client(client, user.id)
    change_password(client, current='WrongPass1!')
    assert 'password_confirm_failed' in event_types(user)


def test_change_password_is_rate_limited(app, user):
    client = app.test_client()
    login_client(client, user.id)
    for _ in range(5):
        change_password(client, current='WrongPass1!')
    assert change_password(client, current='WrongPass1!').status_code == 429


# ── Re-authentication ────────────────────────────────────────────────────────

def test_fresh_login_is_recently_authenticated(app, user):
    client = app.test_client()
    login_client(client, user.id)
    assert request(client, 'get', '/account/security/two-factor/setup').status_code == 200


def test_stale_session_must_confirm_password_for_get(app, user):
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)

    response = request(client, 'get', '/account/security/two-factor/setup')
    assert response.status_code == 302
    location = urlsplit(response.headers['Location'])
    assert location.path == '/account/confirm'
    assert parse_qs(location.query)['next'] == ['/account/security/two-factor/setup']

    assert request(client, 'get', '/account/confirm?next=/account/security/two-factor/setup').status_code == 200
    response = request(client, 'post', '/account/confirm?next=/account/security/two-factor/setup',
                       data={'password': 'TestPass1!'})
    assert response.status_code == 302
    assert response.headers['Location'] == '/account/security/two-factor/setup'
    assert request(client, 'get', '/account/security/two-factor/setup').status_code == 200
    assert 'reauthenticated' in event_types(user)


def test_stale_post_returns_to_referring_page(app, user):
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)
    response = request(client, 'post', '/family/invite', data={'member_name': 'Sam'},
                       headers={'Referer': 'http://localhost/family/?tab=members'})
    assert response.status_code == 302
    location = urlsplit(response.headers['Location'])
    assert location.path == '/account/confirm'
    assert parse_qs(location.query)['next'] == ['/family/?tab=members']
    assert FamilyInvite.query.count() == 0


def test_stale_post_ignores_foreign_referrer(app, user):
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)
    response = request(client, 'post', '/family/invite', data={'member_name': 'Sam'},
                       headers={'Referer': 'https://evil.example/family/'})
    assert parse_qs(urlsplit(response.headers['Location']).query)['next'] == ['/account/security']


def test_reauthenticate_rejects_wrong_password_and_unsafe_next(app, user):
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)

    response = request(client, 'post', '/account/confirm', data={'password': 'WrongPass1!'})
    assert response.status_code == 200
    assert b'Your password was not correct' in response.data
    assert 'password_confirm_failed' in event_types(user)
    assert request(client, 'get', '/account/security/two-factor/setup').status_code == 302

    response = request(client, 'post', '/account/confirm?next=https://evil.example/',
                       data={'password': 'TestPass1!'})
    assert response.headers['Location'] == '/dashboard'


def test_reauthenticate_is_rate_limited(app, user):
    client = app.test_client()
    login_client(client, user.id)
    for _ in range(5):
        request(client, 'post', '/account/confirm', data={'password': 'WrongPass1!'})
    assert request(client, 'post', '/account/confirm', data={'password': 'TestPass1!'}).status_code == 429


def test_reauth_window_is_configurable(app, user):
    client = app.test_client()
    login_client(client, user.id)
    UserSession.query.filter_by(user_id=user.id).update(
        {'reauthenticated_at': _now() - timedelta(minutes=10)}, synchronize_session=False)
    db.session.commit()
    assert request(client, 'get', '/account/security/two-factor/setup').status_code == 200
    app.config['REAUTH_WINDOW_MINUTES'] = 5
    try:
        assert request(client, 'get', '/account/security/two-factor/setup').status_code == 302
    finally:
        app.config['REAUTH_WINDOW_MINUTES'] = 15


def test_reauthenticate_requires_login(app, user):
    response = app.test_client().get('/account/confirm')
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path == '/intro'


@pytest.mark.parametrize('path', [
    '/family/invite',
    '/family/invite/1/revoke',
    '/family/members/999/update',
    '/family/members/999/remove',
])
def test_stale_family_admin_actions_require_password(app, user, path):
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)
    response = request(client, 'post', path, data={'member_name': 'Sam'})
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path == '/account/confirm'


def test_stale_site_admin_must_confirm_for_household_invites_and_admin(app, user):
    enable_two_factor_admin(user)
    client = app.test_client()
    login_client(client, user.id)
    assert request(client, 'get', '/site-admin/household-invites').status_code == 200
    assert request(client, 'get', '/site-admin/console/').status_code == 200

    make_stale(user)
    for path in ('/site-admin/household-invites', '/site-admin/console/', '/site-admin/console/admin_user/'):
        response = request(client, 'get', path)
        assert response.status_code == 302, path
        assert urlsplit(response.headers['Location']).path == '/account/confirm', path

    request(client, 'post', '/account/confirm', data={'password': 'TestPass1!'})
    assert request(client, 'get', '/site-admin/console/admin_user/').status_code == 200


def test_non_admin_is_not_sent_to_reauth_for_admin_panel(app, user):
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'get', '/site-admin/console/')
    assert response.status_code == 302
    assert urlsplit(response.headers['Location']).path != '/account/confirm'


def test_site_admin_without_two_factor_can_reauth_then_setup(app, user):
    user.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)
    response = request(client, 'get', '/account/security/two-factor/setup')
    assert urlsplit(response.headers['Location']).path == '/account/confirm'
    assert request(client, 'get', '/account/confirm').status_code == 200
    request(client, 'post', '/account/confirm?next=/account/security/two-factor/setup',
            data={'password': 'TestPass1!'})
    assert request(client, 'get', '/account/security/two-factor/setup').status_code == 200


# ── Family membership ────────────────────────────────────────────────────────

def test_removed_member_is_signed_out(app, user, family):
    member = make_member(family)
    admin_client, member_client = app.test_client(), app.test_client()
    login_client(admin_client, user.id)
    login_client(member_client, member.id)
    assert is_signed_in(member_client)

    response = request(admin_client, 'post', f'/family/members/{member.id}/remove')
    assert response.status_code == 302
    assert UserSession.query.filter_by(user_id=member.id, revoked_at=None).count() == 0
    assert not is_signed_in(member_client)
    assert 'family_member_removed' in event_types(user)
    assert 'all_sessions_revoked' in event_types(member)


def test_family_invite_and_member_update_are_logged(app, user, family):
    member = make_member(family)
    client = app.test_client()
    login_client(client, user.id)
    request(client, 'post', '/family/invite', data={'member_name': 'Sam', 'role': 'member'})
    invite = FamilyInvite.query.one()
    request(client, 'post', f'/family/invite/{invite.id}/revoke')
    request(client, 'post', f'/family/members/{member.id}/update',
            data={'member_name': 'Member', 'role': 'admin'})
    events = SecurityEvent.query.filter_by(user_id=user.id).all()
    by_type = {event.event_type: event for event in events}
    assert by_type['family_invite_created'].details == 'Sam (member)'
    assert by_type['family_invite_revoked'].details == 'Sam'
    assert by_type['family_member_updated'].details == 'Member (admin)'
    assert by_type['family_member_updated'].family_id == family.id


# ── Security events ──────────────────────────────────────────────────────────

def test_login_and_failures_are_logged(app, user):
    client = app.test_client()
    request(client, 'post', '/login', data={'email': 'admin@example.com', 'password': 'Nope1!'})
    request(client, 'post', '/login', data={'email': 'admin@example.com', 'password': 'TestPass1!'})
    request(client, 'post', '/logout')
    assert event_types(user) == ['login_failed', 'login_success', 'signed_out']
    login = SecurityEvent.query.filter_by(user_id=user.id, event_type='login_success').one()
    assert login.details == 'password'
    assert login.family_id == user.family_id
    assert login.ip_address == '127.0.0.1'
    assert login.user_agent


def test_unknown_email_is_not_logged_against_anyone(app, user):
    client = app.test_client()
    request(client, 'post', '/login', data={'email': 'ghost@example.com', 'password': 'Nope1!'})
    assert SecurityEvent.query.count() == 0


def test_lockout_is_logged(app, user):
    client = app.test_client()
    for _ in range(app.config.get('MAX_LOGIN_ATTEMPTS', 5)):
        limiter.reset()
        request(client, 'post', '/login', data={'email': 'admin@example.com', 'password': 'Nope1!'})
    assert 'account_locked' in event_types(user)


def test_security_page_shows_recent_activity(app, user):
    client = app.test_client()
    request(client, 'post', '/login', data={'email': 'admin@example.com', 'password': 'TestPass1!'})
    page = request(client, 'get', '/account/security')
    assert b'Recent security activity' in page.data
    assert b'Signed in' in page.data
    assert b'Change password' in page.data


def test_events_only_show_for_their_owner(app, user, family):
    member = make_member(family)
    SecurityEventService.record('password_changed', user=member)
    assert SecurityEventService.recent_for_user(user) == []
    assert [e['event_type'] for e in SecurityEventService.recent_for_user(member)] == ['password_changed']


def test_unknown_event_type_is_rejected(app, user):
    with pytest.raises(ValueError):
        SecurityEventService.record('made_up', user=user)


def test_old_events_are_pruned_on_login(app, user):
    old = SecurityEvent(user_id=user.id, event_type='signed_out', created_at=_now() - timedelta(days=400))
    recent = SecurityEvent(user_id=user.id, event_type='signed_out', created_at=_now() - timedelta(days=10))
    db.session.add_all([old, recent])
    db.session.commit()
    old_id, recent_id = old.id, recent.id
    SecurityEventService.record('login_success', user=user)
    assert SecurityEvent.query.filter_by(id=old_id).count() == 0
    assert SecurityEvent.query.filter_by(id=recent_id).count() == 1


def test_admin_security_events_view(app, user):
    enable_two_factor_admin(user)
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'get', '/site-admin/console/admin_securityevent/')
    assert response.status_code == 200
    assert b'two_factor_enabled' in response.data
    assert request(client, 'get', '/site-admin/console/admin_securityevent/new/').status_code in (302, 403, 404)


def test_two_factor_events_are_logged(app, user):
    TwoFactorService.begin_setup(user)
    TwoFactorService.confirm_setup(user, {'code': pyotp.TOTP(user.totp_secret).now()})
    TwoFactorService.regenerate_recovery_codes(user, {'password': 'TestPass1!'})
    assert event_types(user) == ['two_factor_enabled', 'recovery_codes_regenerated']


def test_cli_commands_are_logged(app, user):
    UserSessionService.create(user, user_agent='pytest')
    result = app.test_cli_runner().invoke(args=['sessions', 'revoke', 'admin@example.com'])
    assert result.exit_code == 0, result.output
    event = SecurityEvent.query.filter_by(user_id=user.id, event_type='all_sessions_revoked').one()
    assert event.details == '1 session(s) - server command'

    TwoFactorService.begin_setup(user)
    TwoFactorService.confirm_setup(user, {'code': pyotp.TOTP(user.totp_secret).now()})
    result = app.test_cli_runner().invoke(args=['two-factor', 'reset', 'admin@example.com'])
    assert result.exit_code == 0, result.output
    assert 'two_factor_reset' in event_types(user)
