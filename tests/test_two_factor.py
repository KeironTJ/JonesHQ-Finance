import time

import pyotp
import pytest
from flask import g

from extensions import db, limiter
from models.users import UserRecoveryCode
from services.platform.two_factor_service import TwoFactorService


@pytest.fixture(autouse=True)
def reset_auth_state():
	g.pop('_login_user', None)
	limiter.reset()
	yield
	g.pop('_login_user', None)
	limiter.reset()


def totp_code(user, offset=0):
	step = int(time.time()) // 30 + offset
	return pyotp.TOTP(user.totp_secret).at(step * 30)


def enable_two_factor(user):
	TwoFactorService.begin_setup(user)
	return TwoFactorService.confirm_setup(user, {'code': totp_code(user)})


def password_login(client, email='admin@example.com', password='TestPass1!', **extra):
	data = {'email': email, 'password': password}
	data.update(extra)
	return client.post('/login', data=data)


def is_logged_in(client):
	with client.session_transaction() as session:
		return '_user_id' in session


def test_setup_requires_valid_code_and_returns_recovery_codes(app, user):
	secret = TwoFactorService.begin_setup(user)
	assert TwoFactorService.begin_setup(user) == secret, 'refreshing setup must not change the secret'
	assert not user.two_factor_enabled

	with pytest.raises(ValueError):
		TwoFactorService.confirm_setup(user, {'code': '000000' if totp_code(user) != '000000' else '111111'})
	assert not user.two_factor_enabled

	codes = TwoFactorService.confirm_setup(user, {'code': totp_code(user)})
	assert user.two_factor_enabled
	assert len(codes) == 10 and len(set(codes)) == 10
	assert all(len(code) == 19 and code.count('-') == 3 for code in codes)
	stored = UserRecoveryCode.query.filter_by(user_id=user.id).all()
	assert len(stored) == 10
	assert all(code.replace('-', '') not in {row.code_hash for row in stored} for code in codes)


def test_setup_page_shows_qr_and_confirms(app, user):
	client = app.test_client()
	password_login(client)
	response = client.get('/account/security/two-factor/setup')
	assert response.status_code == 200
	assert b'<svg' in response.data
	assert user.totp_secret.encode() in response.data

	response = client.post('/account/security/two-factor/setup', data={'code': totp_code(user)})
	assert response.status_code == 200
	assert b'Save these now' in response.data
	assert user.two_factor_enabled


def test_login_requires_second_step_when_enabled(app, user):
	enable_two_factor(user)
	client = app.test_client()
	response = password_login(client)
	assert response.status_code == 302
	assert response.headers['Location'].endswith('/login/two-factor')
	assert not is_logged_in(client)

	response = client.post('/login/two-factor', data={'code': 'not-a-code'})
	assert b'That code is not valid' in response.data
	assert not is_logged_in(client)

	response = client.post('/login/two-factor', data={'code': totp_code(user, 1)})
	assert response.status_code == 302
	assert is_logged_in(client)
	with client.session_transaction() as session:
		assert '2fa_pending' not in session


def test_login_preserves_remember_and_safe_next(app, user):
	enable_two_factor(user)
	client = app.test_client()
	client.post('/login?next=/accounts/', data={'email': user.email, 'password': 'TestPass1!', 'remember': 'y'})
	response = client.post('/login/two-factor', data={'code': totp_code(user, 1)})
	assert response.headers['Location'] == '/accounts/'
	assert 'remember_token' in response.headers.get('Set-Cookie', '') or any(
		'remember_token' in value for value in response.headers.getlist('Set-Cookie'))


def test_totp_code_cannot_be_replayed(app, user):
	enable_two_factor(user)
	code = totp_code(user, 1)
	assert TwoFactorService.verify_login(user, {'code': code}) == 'totp'
	with pytest.raises(ValueError):
		TwoFactorService.verify_login(user, {'code': code})
	with pytest.raises(ValueError):
		TwoFactorService.verify_login(user, {'code': totp_code(user, 0)}), 'older steps are rejected too'


def test_recovery_code_works_once_and_is_normalised(app, user):
	codes = enable_two_factor(user)
	assert TwoFactorService.verify_login(user, {'code': f' {codes[0].upper().replace("-", " ")} '}) == 'recovery'
	with pytest.raises(ValueError):
		TwoFactorService.verify_login(user, {'code': codes[0]})
	assert TwoFactorService.remaining_recovery_codes(user) == 9


def test_pending_login_expires(app, user):
	enable_two_factor(user)
	client = app.test_client()
	password_login(client)
	with client.session_transaction() as session:
		pending = session['2fa_pending']
		pending['started'] -= 301
		session['2fa_pending'] = pending
	response = client.post('/login/two-factor', data={'code': totp_code(user, 1)})
	assert response.status_code == 302
	assert response.headers['Location'].endswith('/login')
	assert not is_logged_in(client)


def test_two_factor_page_without_pending_login_redirects(app, user):
	response = app.test_client().get('/login/two-factor')
	assert response.status_code == 302
	assert response.headers['Location'].endswith('/login')


def test_inactive_user_cannot_finish_second_step(app, user):
	enable_two_factor(user)
	client = app.test_client()
	password_login(client)
	user.is_active = False
	db.session.commit()
	client.post('/login/two-factor', data={'code': totp_code(user, 1)})
	assert not is_logged_in(client)


def test_second_step_is_rate_limited_per_user(app, user):
	enable_two_factor(user)
	client = app.test_client()
	password_login(client)
	statuses = [client.post('/login/two-factor', data={'code': 'bad'}).status_code for _ in range(6)]
	assert statuses[:5] == [200] * 5
	assert statuses[5] == 429


def test_disable_requires_password_and_code(app, user):
	enable_two_factor(user)
	with pytest.raises(ValueError):
		TwoFactorService.disable(user, {'password': 'WrongPass1!', 'code': totp_code(user, 1)})
	with pytest.raises(ValueError):
		TwoFactorService.disable(user, {'password': 'TestPass1!', 'code': 'bad'})
	assert user.two_factor_enabled

	TwoFactorService.disable(user, {'password': 'TestPass1!', 'code': totp_code(user, 1)})
	assert not user.two_factor_enabled
	assert user.totp_secret is None
	assert UserRecoveryCode.query.filter_by(user_id=user.id).count() == 0


def test_regenerate_recovery_codes_replaces_old_ones(app, user):
	old_codes = enable_two_factor(user)
	with pytest.raises(ValueError):
		TwoFactorService.regenerate_recovery_codes(user, {'password': 'WrongPass1!'})
	new_codes = TwoFactorService.regenerate_recovery_codes(user, {'password': 'TestPass1!'})
	assert set(new_codes).isdisjoint(old_codes)
	with pytest.raises(ValueError):
		TwoFactorService.verify_login(user, {'code': old_codes[0]})
	assert TwoFactorService.verify_login(user, {'code': new_codes[0]}) == 'recovery'


def test_site_admin_without_two_factor_is_forced_to_setup(app, user):
	user.is_site_admin = True
	db.session.commit()
	client = app.test_client()
	password_login(client)
	response = client.get('/dashboard/')
	assert response.status_code == 302
	assert response.headers['Location'].endswith('/account/security/two-factor/setup')
	assert client.get('/admin/').status_code == 302
	assert client.get('/account/security/two-factor/setup').status_code == 200


def test_site_admin_cannot_disable_two_factor(app, user):
	user.is_site_admin = True
	db.session.commit()
	enable_two_factor(user)
	with pytest.raises(ValueError, match='Site admins'):
		TwoFactorService.disable(user, {'password': 'TestPass1!', 'code': totp_code(user, 1)})
	assert user.two_factor_enabled


def test_cli_reset(app, user):
	enable_two_factor(user)
	result = app.test_cli_runner().invoke(args=['two-factor', 'reset', 'ADMIN@example.com'])
	assert result.exit_code == 0, result.output
	assert not user.two_factor_enabled
	assert UserRecoveryCode.query.filter_by(user_id=user.id).count() == 0

	result = app.test_cli_runner().invoke(args=['two-factor', 'reset', 'nobody@example.com'])
	assert result.exit_code == 1


def test_admin_panel_never_shows_two_factor_secret(app, user):
	user.is_site_admin = True
	db.session.commit()
	enable_two_factor(user)
	client = app.test_client()
	password_login(client)
	client.post('/login/two-factor', data={'code': totp_code(user, 1)})
	assert is_logged_in(client)

	for path in (
		'/admin/admin_user/',
		f'/admin/admin_user/details/?id={user.id}',
		'/admin/admin_user/export/csv/',
	):
		response = client.get(path)
		assert response.status_code == 200, path
		assert user.totp_secret.encode() not in response.data, path
		assert b'totp_secret' not in response.data, path


def test_account_security_page(app, user):
	client = app.test_client()
	password_login(client)
	response = client.get('/account/security')
	assert response.status_code == 200
	assert b'Turn on two-factor login' in response.data
