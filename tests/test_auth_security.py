from datetime import datetime, timedelta, timezone
import re

import pytest
from flask import Flask, g

from app import create_app
from config import ProductionConfig
from extensions import db, limiter
from models.family import Family, FamilyInvite
from models.users import User
from services.platform.auth_service import AuthService


@pytest.fixture(autouse=True)
def reset_auth_state():
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    g.pop('csrf_valid', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    g.pop('csrf_valid', None)
    limiter.reset()


def login(client, **overrides):
    data = {'email': 'admin@example.com', 'password': 'TestPass1!'}
    data.update(overrides)
    return client.post('/login', data=data)


@pytest.mark.parametrize('state', ['unknown', 'wrong_password', 'locked', 'inactive'])
def test_login_rejections_use_identical_public_message(app, user, state):
    if state == 'locked':
        user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)
    elif state == 'inactive':
        user.is_active = False
    db.session.commit()
    client = app.test_client()
    response = login(
        client,
        email='unknown@example.com' if state == 'unknown' else user.email,
        password='WrongPass1!',
    )
    assert response.status_code == 200
    assert b'Invalid email or password.' in response.data
    assert b'attempts remaining' not in response.data
    assert b'Account temporarily locked' not in response.data
    assert b'deactivated' not in response.data
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_successful_login_normalizes_email_and_clears_attempts(app, user):
    user.failed_login_attempts = 2
    db.session.commit()
    client = app.test_client()
    response = login(client, email=' ADMIN@EXAMPLE.COM ')
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session['_user_id'] == str(user.id)
    db.session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.last_login is not None


def test_expired_lockout_starts_new_attempt_window(app, user):
    user.failed_login_attempts = app.config['MAX_LOGIN_ATTEMPTS']
    user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()
    login(app.test_client(), password='WrongPass1!')
    db.session.refresh(user)
    assert user.failed_login_attempts == 1
    assert not user.is_locked()


@pytest.mark.parametrize('target', [
    'https://example.com', '//example.com', 'javascript:alert(1)',
    '/\\example.com', '/%5cexample.com',
])
def test_login_rejects_unsafe_redirects(app, user, target):
    response = app.test_client().post(
        '/login', query_string={'next': target},
        data={'email': user.email, 'password': 'TestPass1!'},
    )
    assert response.status_code == 302
    assert response.location.endswith('/dashboard')


def test_login_preserves_local_redirect(app, user):
    response = app.test_client().post(
        '/login', query_string={'next': '/accounts/?view=all'},
        data={'email': user.email, 'password': 'TestPass1!'},
    )
    assert response.location == '/accounts/?view=all'


def test_login_rate_limit_is_actually_enforced(app):
    client = app.test_client()
    for _ in range(10):
        assert login(client, email='unknown@example.com').status_code == 200
    response = login(client, email='unknown@example.com')
    assert response.status_code == 429


def test_login_account_limit_cannot_be_bypassed_by_changing_ip(app):
    client = app.test_client()
    for number in range(20):
        response = client.post(
            '/login', data={'email': 'unknown@example.com', 'password': 'WrongPass1!'},
            environ_overrides={'REMOTE_ADDR': f'192.0.2.{number + 1}'},
        )
        assert response.status_code == 200
    response = client.post(
        '/login', data={'email': ' UNKNOWN@EXAMPLE.COM ', 'password': 'WrongPass1!'},
        environ_overrides={'REMOTE_ADDR': '192.0.2.100'},
    )
    assert response.status_code == 429


def test_login_get_requests_do_not_consume_attempt_limit(app):
    client = app.test_client()
    for _ in range(12):
        assert client.get('/login').status_code == 200
    assert login(client, email='unknown@example.com').status_code == 200


def test_forwarded_ip_is_not_trusted_by_default(app):
    client = app.test_client()
    for number in range(10):
        response = client.post(
            '/login', headers={'X-Forwarded-For': f'192.0.2.{number + 1}'},
            data={'email': 'unknown@example.com', 'password': 'WrongPass1!'},
        )
        assert response.status_code == 200
    assert login(client, email='unknown@example.com').status_code == 429


def test_logout_requires_post_and_csrf(app, user, monkeypatch):
    client = app.test_client()
    login(client)
    assert client.get('/logout').status_code == 405
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    assert client.post('/logout').status_code == 400
    with client.session_transaction() as session:
        assert session['_user_id'] == str(user.id)
    g.pop('csrf_token', None)
    page = client.get('/accounts')
    token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    response = client.post('/logout', data={'csrf_token': token})
    assert response.status_code == 302
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_logout_clears_remember_cookie_and_session(app, user):
    client = app.test_client()
    login(client, remember='y')
    response = client.post('/logout')
    assert response.status_code == 302
    assert any('remember_token=;' in cookie for cookie in response.headers.getlist('Set-Cookie'))
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_deactivation_rejects_existing_session(app, user):
    client = app.test_client()
    login(client)
    user.is_active = False
    db.session.commit()
    g.pop('_login_user', None)
    response = client.get('/accounts')
    assert response.status_code == 302
    assert '/intro' in response.location


def test_cookie_flags_and_remember_lifetime(app, user, monkeypatch):
    for key in ('SESSION_COOKIE_SECURE', 'REMEMBER_COOKIE_SECURE'):
        monkeypatch.setitem(app.config, key, True)
    response = login(app.test_client(), remember='y')
    cookies = response.headers.getlist('Set-Cookie')
    for name in ('session', 'remember_token'):
        cookie = next(value for value in cookies if value.startswith(name + '='))
        assert 'Secure' in cookie
        assert 'HttpOnly' in cookie
        assert 'SameSite=Lax' in cookie
    assert app.config['REMEMBER_COOKIE_DURATION'] == timedelta(days=7)


def test_sensitive_responses_are_not_cacheable_but_static_assets_are(app, user):
    client = app.test_client()
    assert client.get('/login').headers['Cache-Control'] == 'no-store'
    login(client)
    response = client.get('/accounts')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert client.post('/logout').headers['Cache-Control'] == 'no-store'
    assert 'no-store' not in client.get('/static/js/main.js').headers['Cache-Control']


def test_registration_service_enforces_password_policy_before_writes(app):
    with pytest.raises(ValueError, match='Password must contain'):
        AuthService.register_user('Household', 'weak@example.com', 'New User', 'weakpass')
    assert Family.query.count() == 0
    assert User.query.count() == 0


def test_invitation_uses_registration_password_policy(app, family, user):
    invite = FamilyInvite(
        family_id=family.id, member_name='Member', created_by_id=user.id,
    )
    db.session.add(invite)
    db.session.commit()
    response = app.test_client().post(f'/family/join/{invite.token}', data={
        'name': 'Member', 'email': 'member@example.com',
        'password': 'weakpass', 'confirm_password': 'weakpass',
    })
    assert response.status_code == 200
    assert b'Password must contain' in response.data
    assert User.query.filter_by(email='member@example.com').first() is None
    db.session.refresh(invite)
    assert invite.used_at is None


def test_invitation_posts_are_rate_limited(app, family, user):
    invite = FamilyInvite(
        family_id=family.id, member_name='Member', created_by_id=user.id,
    )
    db.session.add(invite)
    db.session.commit()
    client = app.test_client()
    for _ in range(5):
        assert client.post(f'/family/join/{invite.token}', data={}).status_code == 200
    assert client.post(f'/family/join/{invite.token}', data={}).status_code == 429


@pytest.mark.parametrize('invalid_key', [
    'SECRET_KEY', 'SQLALCHEMY_DATABASE_URI', 'RATELIMIT_STORAGE_URI',
])
def test_production_startup_rejects_missing_security_settings(app, monkeypatch, invalid_key):
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(ProductionConfig, 'SQLALCHEMY_DATABASE_URI', 'sqlite:///:memory:')
    monkeypatch.setattr(ProductionConfig, 'RATELIMIT_STORAGE_URI', 'redis://localhost:6379/0', raising=False)
    monkeypatch.setattr(ProductionConfig, invalid_key, None)
    with pytest.raises(ValueError, match=invalid_key):
        create_app('production')


def test_production_rejects_process_local_rate_limit_storage(app):
    application = Flask(__name__)
    application.config.from_object(ProductionConfig)
    application.config.update(
        SECRET_KEY='a' * 64, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        RATELIMIT_STORAGE_URI='memory://',
    )
    with pytest.raises(ValueError, match='RATELIMIT_STORAGE_URI'):
        ProductionConfig.init_app(application)
