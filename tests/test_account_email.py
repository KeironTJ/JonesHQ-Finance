import re
import time
from datetime import timedelta
from unittest import mock

import pyotp
import pytest
from flask import g

from extensions import db, limiter
from models.users import SecurityEvent, User, UserSession
from services.platform.email_service import EmailService
from services.platform.email_verification_service import EmailVerificationService
from services.platform.password_reset_service import PasswordResetService
from services.platform.two_factor_service import TwoFactorService
from services.platform.user_session_service import _now
from tests.auth_helpers import login_client


NEW_PASSWORD = 'BrandNew#Pass42'


@pytest.fixture(autouse=True)
def reset_state():
    g.pop('_login_user', None)
    limiter.reset()
    EmailService.outbox().clear()
    yield
    g.pop('_login_user', None)
    limiter.reset()
    EmailService.outbox().clear()


def request(client, method, path, **kwargs):
    g.pop('_login_user', None)
    return getattr(client, method)(path, **kwargs)


def outbox():
    return EmailService.outbox()


def link_in(message):
    match = re.search(r'https://\S+', message.get_content())
    assert match, message.get_content()
    return match.group(0)


def path_of(link):
    return link.replace('https://finance.example.com', '')


def event_types(user):
    return [event.event_type for event in
            SecurityEvent.query.filter_by(user_id=user.id).order_by(SecurityEvent.id).all()]


def request_reset(client, email='admin@example.com'):
    return request(client, 'post', '/forgot-password', data={'email': email})


def open_reset_link(client, user):
    request_reset(client, user.email)
    return request(client, 'get', path_of(link_in(outbox()[-1])))


def submit_new_password(client, new=NEW_PASSWORD, confirm=None):
    return request(client, 'post', '/reset-password', data={
        'new_password': new, 'confirm_password': new if confirm is None else confirm})


def login(client, email='admin@example.com', password='TestPass1!', agent='Firefox/120 (Windows NT 10.0)'):
    return request(client, 'post', '/login', data={'email': email, 'password': password},
                   headers={'User-Agent': agent})


# ── Email service ────────────────────────────────────────────────────────────

def test_external_url_uses_app_base_url_not_host_header(app):
    with app.test_request_context('/', headers={'Host': 'evil.example.net'}):
        link = EmailService.external_url('auth.login')
    assert link == 'https://finance.example.com/login'


def test_external_url_keeps_base_url_path(app, monkeypatch):
    monkeypatch.setitem(app.config, 'APP_BASE_URL', 'https://example.com/finance')
    assert EmailService.external_url('auth.login') == 'https://example.com/finance/login'


def test_external_url_requires_base_url_outside_request(app, monkeypatch):
    monkeypatch.setitem(app.config, 'APP_BASE_URL', '')
    with pytest.raises(ValueError):
        EmailService.external_url('auth.login')


def test_send_is_noop_when_email_not_configured(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_SERVER', '')
    assert EmailService.send('a@example.com', 'Hi', 'test') is False
    assert outbox() == []


def test_send_builds_plain_text_message(app):
    assert EmailService.send('a@example.com', 'Hello', 'test', base_url='https://x')
    message = outbox()[0]
    assert message['To'] == 'a@example.com'
    assert message['From'] == 'Family HQ <noreply@example.com>'
    assert message['Message-ID'].endswith('@example.com>')
    assert 'outgoing email is working' in message.get_content()


def test_deliver_uses_ssl_and_login(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USERNAME', 'resend')
    monkeypatch.setitem(app.config, 'MAIL_PASSWORD', 're_key')
    with mock.patch('smtplib.SMTP_SSL') as smtp_ssl:
        EmailService._deliver(app, mock.Mock())
    smtp_ssl.assert_called_once()
    assert smtp_ssl.call_args.args[:2] == ('smtp.test.invalid', 465)
    smtp_ssl.return_value.login.assert_called_once_with('resend', 're_key')


def test_deliver_with_starttls(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_USE_SSL', False)
    monkeypatch.setitem(app.config, 'MAIL_USE_TLS', True)
    monkeypatch.setitem(app.config, 'MAIL_PORT', 587)
    with mock.patch('smtplib.SMTP') as smtp:
        EmailService._deliver(app, mock.Mock())
    smtp.return_value.starttls.assert_called_once()


# ── Forgot password ──────────────────────────────────────────────────────────

def test_login_page_links_to_forgot_password(app):
    response = app.test_client().get('/login')
    assert b'/forgot-password' in response.data


def test_forgot_password_emails_link_with_generic_response(app, user):
    response = request_reset(app.test_client())
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert len(outbox()) == 1
    assert outbox()[0]['To'] == user.email
    assert link_in(outbox()[0]).startswith('https://finance.example.com/reset-password/')
    assert 'password_reset_requested' in event_types(user)


def test_forgot_password_unknown_email_sends_nothing_same_response(app, user):
    client = app.test_client()
    known = request_reset(client)
    unknown = request_reset(client, 'nobody@example.com')
    assert unknown.status_code == known.status_code == 302
    assert unknown.headers['Location'] == known.headers['Location']
    assert len(outbox()) == 1


def test_forgot_password_ignores_deactivated_user(app, user):
    user.is_active = False
    db.session.commit()
    request_reset(app.test_client())
    assert outbox() == []


def test_forgot_password_rate_limited_per_email(app, user):
    client = app.test_client()
    statuses = [request_reset(client).status_code for _ in range(4)]
    assert statuses[:3] == [302, 302, 302]
    assert statuses[3] == 429


def test_forgot_password_without_email_configured(app, user, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_SERVER', '')
    response = app.test_client().get('/forgot-password')
    assert b'Ask your site admin' in response.data
    assert b'<form' not in response.data.split(b'auth-card-body')[1]


def test_forgot_password_redirects_signed_in_user(app, user):
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'get', '/forgot-password')
    assert response.headers['Location'].endswith('/account/security')


# ── Reset password ───────────────────────────────────────────────────────────

def test_reset_link_moves_token_out_of_url(app, user):
    client = app.test_client()
    response = open_reset_link(client, user)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/reset-password')
    page = request(client, 'get', '/reset-password')
    assert page.status_code == 200
    assert b'Choose a new password' in page.data
    assert b'new_password' in page.data


def test_reset_password_changes_password_and_signs_out_everywhere(app, user):
    other = app.test_client()
    login_client(other, user.id)
    user.failed_login_attempts = 4
    user.locked_until = _now() + timedelta(minutes=10)
    db.session.commit()

    client = app.test_client()
    open_reset_link(client, user)
    response = submit_new_password(client)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    db.session.refresh(user)
    assert user.check_password(NEW_PASSWORD)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    assert user.email_verified_at is not None
    assert UserSession.query.filter_by(user_id=user.id, revoked_at=None).count() == 0
    assert request(other, 'get', '/account/security').status_code == 302
    assert 'password_reset' in event_types(user)
    with client.session_transaction() as session:
        assert 'password_reset_token' not in session


def test_reset_link_works_only_once(app, user):
    client = app.test_client()
    request_reset(client)
    link = path_of(link_in(outbox()[-1]))
    request(client, 'get', link)
    submit_new_password(client)

    request(client, 'get', link)
    page = request(client, 'get', '/reset-password')
    assert b'invalid, has expired or has already been used' in page.data
    assert submit_new_password(client, 'Another#Pass99').status_code == 200
    db.session.refresh(user)
    assert user.check_password(NEW_PASSWORD)


def test_old_reset_link_dies_when_password_changed_another_way(app, user):
    token = PasswordResetService.create_token(user, 60)
    user.set_password('Changed#Else1')
    db.session.commit()
    assert PasswordResetService.get_user(token) is None


def test_reset_link_expires(app, user):
    token = PasswordResetService.create_token(user, 60)
    with mock.patch('time.time', return_value=time.time() + 61 * 60):
        assert PasswordResetService.get_user(token) is None
    assert PasswordResetService.get_user(token) == user


def test_tampered_or_garbage_reset_tokens_rejected(app, user):
    token = PasswordResetService.create_token(user, 60)
    assert PasswordResetService.get_user(token[:-2] + 'xx') is None
    assert PasswordResetService.get_user('nonsense') is None
    assert PasswordResetService.get_user('a' * 600) is None
    assert PasswordResetService.get_user(None) is None


def test_reset_token_rejected_for_deactivated_user(app, user):
    token = PasswordResetService.create_token(user, 60)
    user.is_active = False
    db.session.commit()
    assert PasswordResetService.get_user(token) is None


def test_reset_password_enforces_policy_and_match(app, user):
    client = app.test_client()
    open_reset_link(client, user)
    weak = submit_new_password(client, 'short')
    assert weak.status_code == 200
    assert b'Password must contain' in weak.data
    mismatch = submit_new_password(client, NEW_PASSWORD, 'Different#Pass1')
    assert b'do not match' in mismatch.data
    db.session.refresh(user)
    assert user.check_password('TestPass1!')


def test_reset_page_without_token_shows_invalid(app):
    page = app.test_client().get('/reset-password')
    assert b'Request a new link' in page.data


def test_reset_still_requires_two_factor(app, user):
    TwoFactorService.begin_setup(user)
    TwoFactorService.confirm_setup(user, {'code': pyotp.TOTP(user.totp_secret).now()})
    client = app.test_client()
    open_reset_link(client, user)
    submit_new_password(client)

    response = login(client, password=NEW_PASSWORD)
    assert response.headers['Location'].endswith('/login/two-factor')
    assert request(client, 'get', '/account/security').status_code == 302


def test_reset_signs_out_current_browser(app, user):
    client = app.test_client()
    login_client(client, user.id)
    token = PasswordResetService.create_token(user, 60)
    request(client, 'get', f'/reset-password/{token}')
    submit_new_password(client)
    assert request(client, 'get', '/account/security').status_code == 302


# ── Admin reset link ─────────────────────────────────────────────────────────

def test_admin_reset_link_lasts_longer_and_does_not_verify_email(app, user):
    _, link, hours = PasswordResetService.create_admin_link(user.email)
    assert hours == 24
    token = link.rsplit('/', 1)[1]
    with mock.patch('time.time', return_value=time.time() + 23 * 3600):
        assert PasswordResetService.get_user(token) == user
    PasswordResetService.reset_password(token, {'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
    db.session.refresh(user)
    assert user.email_verified_at is None
    assert 'password_reset_link_created' in event_types(user)


def test_admin_reset_link_unknown_or_inactive_user(app, user):
    with pytest.raises(ValueError):
        PasswordResetService.create_admin_link('nobody@example.com')
    user.is_active = False
    db.session.commit()
    with pytest.raises(ValueError):
        PasswordResetService.create_admin_link(user.email)


def test_cli_users_reset_link(app, user):
    result = app.test_cli_runner().invoke(args=['users', 'reset-link', user.email])
    assert result.exit_code == 0
    assert 'https://finance.example.com/reset-password/' in result.output


def test_cli_users_reset_link_unknown(app):
    result = app.test_cli_runner().invoke(args=['users', 'reset-link', 'nobody@example.com'])
    assert result.exit_code == 1


def test_cli_email_test(app):
    result = app.test_cli_runner().invoke(args=['email', 'test', 'me@example.com'])
    assert result.exit_code == 0
    assert outbox()[-1]['To'] == 'me@example.com'


def test_cli_email_test_not_configured(app, monkeypatch):
    monkeypatch.setitem(app.config, 'MAIL_SERVER', '')
    result = app.test_cli_runner().invoke(args=['email', 'test', 'me@example.com'])
    assert result.exit_code == 1


# ── Email verification ───────────────────────────────────────────────────────

def test_verification_link_confirms_email(app, user):
    assert EmailVerificationService.send_verification(user)
    response = request(app.test_client(), 'get', path_of(link_in(outbox()[-1])))
    assert response.headers['Location'].endswith('/login')
    db.session.refresh(user)
    assert user.email_verified_at is not None
    assert 'email_verified' in event_types(user)
    assert EmailVerificationService.send_verification(user) is False


def test_verification_link_invalid_after_email_change(app, user):
    token = EmailVerificationService.create_token(user)
    user.email = 'changed@example.com'
    db.session.commit()
    with pytest.raises(ValueError):
        EmailVerificationService.verify(token)


def test_verification_link_expires(app, user):
    token = EmailVerificationService.create_token(user)
    with mock.patch('time.time', return_value=time.time() + 4 * 86400):
        with pytest.raises(ValueError, match='expired'):
            EmailVerificationService.verify(token)


def test_bad_verification_link_flashes_error(app, user):
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'get', '/verify-email/garbage')
    assert response.headers['Location'].endswith('/account/security')
    db.session.refresh(user)
    assert user.email_verified_at is None


def test_account_security_resend_verification(app, user):
    client = app.test_client()
    login_client(client, user.id)
    page = request(client, 'get', '/account/security')
    assert b'Not confirmed' in page.data
    assert b'Send confirmation email' in page.data
    response = request(client, 'post', '/account/security/verify-email')
    assert response.status_code == 302
    assert len(outbox()) == 1
    statuses = [request(client, 'post', '/account/security/verify-email').status_code for _ in range(3)]
    assert statuses[-1] == 429


def test_registration_sends_verification(app, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_OPEN_REGISTRATION', True)
    response = app.test_client().post('/register', data={
        'household_name': 'Smiths', 'name': 'Sam Smith', 'email': 'sam@example.com',
        'password': 'Register#Pass1', 'confirm_password': 'Register#Pass1',
    })
    assert response.status_code == 302
    assert [message['To'] for message in outbox()] == ['sam@example.com']
    assert '/verify-email/' in link_in(outbox()[0])


# ── Security alerts ──────────────────────────────────────────────────────────

def alerts():
    return [message for message in outbox() if 'security change' in message.get_content()]


def test_first_sign_in_does_not_alert(app, user):
    login(app.test_client())
    assert alerts() == []


def test_sign_in_from_new_browser_alerts_same_browser_does_not(app, user):
    login(app.test_client())
    login(app.test_client())
    assert alerts() == []
    login(app.test_client(), agent='Mozilla/5.0 (iPhone) Safari/604.1')
    assert len(alerts()) == 1
    message = alerts()[0]
    assert message['Subject'] == 'New sign-in to your Family HQ account'
    assert 'Safari on iPhone' in message.get_content()
    assert 'https://finance.example.com/account/security' in message.get_content()


def test_password_change_alerts(app, user):
    client = app.test_client()
    login_client(client, user.id)
    request(client, 'post', '/account/security/password', data={
        'current_password': 'TestPass1!', 'new_password': NEW_PASSWORD, 'confirm_password': NEW_PASSWORD})
    assert [message['Subject'] for message in alerts()] == ['Your Family HQ password was changed']


def test_password_reset_alerts(app, user):
    client = app.test_client()
    open_reset_link(client, user)
    submit_new_password(client)
    assert [message['Subject'] for message in alerts()] == ['Your Family HQ password was reset']


def test_two_factor_changes_alert(app, user):
    from services.platform.security_event_service import SecurityEventService
    for event in ('two_factor_enabled', 'two_factor_disabled', 'two_factor_reset', 'recovery_codes_regenerated'):
        SecurityEventService.record(event, user=user)
    assert len(alerts()) == 4


def test_alert_failure_does_not_break_event_recording(app, user, monkeypatch):
    from services.platform.security_event_service import SecurityEventService

    def boom(*args, **kwargs):
        raise RuntimeError('smtp down')

    monkeypatch.setattr(EmailService, 'send', boom)
    SecurityEventService.record('password_changed', user=user)
    assert 'password_changed' in event_types(user)


def test_no_alerts_when_email_off(app, user, monkeypatch):
    from services.platform.security_event_service import SecurityEventService
    monkeypatch.setitem(app.config, 'MAIL_SERVER', '')
    SecurityEventService.record('password_changed', user=user)
    assert outbox() == []


# ── Configuration ────────────────────────────────────────────────────────────

def _app_from(config_class, **overrides):
    from flask import Flask
    application = Flask(__name__)
    application.config.from_object(config_class)
    application.config.update(overrides)
    return application


def test_production_requires_https_base_url_with_email(app):
    from config import ProductionConfig
    base = dict(SECRET_KEY='a' * 64, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
                RATELIMIT_STORAGE_URI='redis://localhost:6379/0',
                MAIL_SERVER='smtp.resend.com', MAIL_FROM='Family HQ <noreply@example.com>')
    for bad in ('', 'http://finance.example.com'):
        with pytest.raises(ValueError, match='APP_BASE_URL'):
            ProductionConfig.init_app(_app_from(ProductionConfig, APP_BASE_URL=bad, **base))
    ProductionConfig.init_app(_app_from(ProductionConfig, APP_BASE_URL='https://finance.example.com', **base))


def test_mail_settings_validated(app):
    from config import Config
    with pytest.raises(ValueError, match='MAIL_FROM'):
        Config.init_app(_app_from(Config, MAIL_SERVER='smtp.resend.com', MAIL_FROM=''))
    with pytest.raises(ValueError, match='MAIL_USE_SSL'):
        Config.init_app(_app_from(Config, MAIL_SERVER='smtp.resend.com', MAIL_FROM='a@b.c',
                                  MAIL_USE_SSL=True, MAIL_USE_TLS=True))