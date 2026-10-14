from datetime import timedelta

import pytest
from flask import g

from extensions import db, limiter
from models.users import User, UserSession
from services.platform.two_factor_service import TwoFactorService
from services.platform.user_session_service import UserSessionService, _now, describe_user_agent
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


def password_login(client, **extra):
    data = {'email': 'admin@example.com', 'password': 'TestPass1!'}
    data.update(extra)
    return request(client, 'post', '/login', data=data)


def make_other_user(family):
    other = User(email='other@example.com', name='Other', role='member', family_id=family.id)
    other.set_password('OtherPass1!')
    db.session.add(other)
    db.session.commit()
    return other


def test_login_creates_session_record_and_stores_token(app, user):
    client = app.test_client()
    password_login(client, remember='y')
    records = UserSession.query.filter_by(user_id=user.id).all()
    assert len(records) == 1
    assert records[0].remember is True
    with client.session_transaction() as session:
        user_part, token = session['_user_id'].split(':', 1)
    assert user_part == str(user.id)
    assert token and records[0].token_hash != token
    assert is_signed_in(client)


def test_revoked_session_is_signed_out(app, user):
    client = app.test_client()
    login_client(client, user.id)
    assert is_signed_in(client)
    UserSessionService.revoke_all(user)
    assert not is_signed_in(client)


def test_revoked_remember_cookie_stops_working(app, user):
    client = app.test_client()
    password_login(client, remember='y')
    cookie = client.get_cookie('remember_token')
    assert cookie is not None

    fresh = app.test_client()
    fresh.set_cookie('remember_token', cookie.value)
    assert is_signed_in(fresh), 'remember cookie should restore the login'

    UserSessionService.revoke_all(user)
    revoked = app.test_client()
    revoked.set_cookie('remember_token', cookie.value)
    assert not is_signed_in(revoked)


def test_idle_timeout_applies_only_without_remember(app, user):
    normal = app.test_client()
    remembered = app.test_client()
    login_client(normal, user.id)
    login_client(remembered, user.id, remember=True)
    stale = _now() - timedelta(minutes=app.config['SESSION_IDLE_MINUTES'] + 1)
    UserSession.query.update({UserSession.last_seen_at: stale})
    db.session.commit()

    assert not is_signed_in(normal)
    assert is_signed_in(remembered)


def test_absolute_expiry_signs_out(app, user):
    client = app.test_client()
    login_client(client, user.id, remember=True)
    UserSession.query.update({UserSession.expires_at: _now() - timedelta(seconds=1)})
    db.session.commit()
    assert not is_signed_in(client)


def test_legacy_and_mismatched_ids_are_rejected(app, family, user):
    assert UserSessionService.load_user(str(user.id)) is None
    assert UserSessionService.load_user(f'{user.id}:') is None
    assert UserSessionService.load_user(None) is None

    other = make_other_user(family)
    _, token = UserSessionService.create(user)
    assert UserSessionService.load_user(f'{other.id}:{token}') is None
    assert UserSessionService.load_user(f'{user.id}:{token}').id == user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True
    assert not is_signed_in(client)


def test_inactive_user_session_is_rejected(app, user):
    _, token = UserSessionService.create(user)
    user.is_active = False
    db.session.commit()
    assert UserSessionService.load_user(f'{user.id}:{token}') is None


def test_logout_revokes_record(app, user):
    client = app.test_client()
    password_login(client)
    request(client, 'post', '/logout')
    record = UserSession.query.filter_by(user_id=user.id).one()
    assert record.revoked_at is not None


def test_revoke_others_keeps_current_session(app, user):
    current = app.test_client()
    other = app.test_client()
    login_client(current, user.id)
    login_client(other, user.id)

    response = request(current, 'post', '/account/security/sessions/revoke-others')
    assert response.status_code == 302
    assert is_signed_in(current)
    assert not is_signed_in(other)


def test_revoke_specific_session_and_current_session(app, user):
    current = app.test_client()
    other = app.test_client()
    login_client(current, user.id)
    login_client(other, user.id)
    current_id, other_id = [record.id for record in UserSession.query.order_by(UserSession.id)]

    response = request(current, 'post', f'/account/security/sessions/{other_id}/revoke')
    assert response.status_code == 302
    assert '/account/security' in response.location
    assert not is_signed_in(other)
    assert is_signed_in(current)

    response = request(current, 'post', f'/account/security/sessions/{current_id}/revoke')
    assert '/login' in response.location
    assert not is_signed_in(current)


def test_cannot_revoke_another_users_session(app, family, user):
    other = make_other_user(family)
    other_client = app.test_client()
    login_client(other_client, other.id)
    other_record = UserSession.query.filter_by(user_id=other.id).one()

    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'post', f'/account/security/sessions/{other_record.id}/revoke', follow_redirects=True)
    assert b'not found' in response.data
    assert is_signed_in(other_client)


def test_account_security_lists_devices(app, user):
    client = app.test_client()
    login_client(client, user.id)
    UserSessionService.create(
        user, user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari/604.1')
    response = request(client, 'get', '/account/security')
    assert b'This device' in response.data
    assert b'Safari on iPhone' in response.data
    assert b'Sign out all other devices' in response.data


def test_describe_user_agent():
    chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
    assert describe_user_agent(chrome) == 'Chrome on Windows'
    assert describe_user_agent(None) == 'Unknown browser on unknown device'


def test_enabling_two_factor_signs_out_other_sessions(app, user):
    import pyotp, time
    current = app.test_client()
    other = app.test_client()
    login_client(current, user.id)
    login_client(other, user.id)

    request(current, 'get', '/account/security/two-factor/setup')
    db.session.refresh(user)
    code = pyotp.TOTP(user.totp_secret).at(int(time.time()))
    response = request(current, 'post', '/account/security/two-factor/setup', data={'code': code})
    assert b'1 other session signed out' in response.data
    assert is_signed_in(current)
    assert not is_signed_in(other)


def test_sessions_revoke_cli(app, user):
    client = app.test_client()
    login_client(client, user.id)
    result = app.test_cli_runner().invoke(args=['sessions', 'revoke', 'ADMIN@example.com'])
    assert result.exit_code == 0
    assert '1 session(s)' in result.output
    assert not is_signed_in(client)

    result = app.test_cli_runner().invoke(args=['sessions', 'revoke', 'nobody@example.com'])
    assert result.exit_code != 0


def test_activity_updates_last_seen_after_interval(app, user):
    client = app.test_client()
    login_client(client, user.id)
    record = UserSession.query.filter_by(user_id=user.id).one()
    old = _now() - timedelta(minutes=5)
    UserSession.query.update({UserSession.last_seen_at: old})
    db.session.commit()

    assert is_signed_in(client)
    db.session.refresh(record)
    assert record.last_seen_at > old


def test_create_prunes_old_records(app, user):
    old, _ = UserSessionService.create(user)
    old.revoked_at = _now() - timedelta(days=31)
    db.session.commit()
    old_id = old.id
    UserSessionService.create(user)
    assert UserSession.query.filter_by(id=old_id).count() == 0


def test_admin_sessions_view_hides_token_hash(app, user):
    user.totp_secret = TwoFactorService.begin_setup(user)
    user.totp_enabled_at = _now()
    user.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    record = UserSession.query.filter_by(user_id=user.id).one()

    response = request(client, 'get', '/admin/admin_usersession/')
    assert response.status_code == 200
    assert b'pytest' in response.data
    assert record.token_hash.encode() not in response.data
