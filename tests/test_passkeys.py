import hashlib
import importlib
import json
from datetime import datetime, timedelta, timezone

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from flask import g
from webauthn.helpers import bytes_to_base64url

from extensions import db, limiter
from models.family import Family
from models.passkeys import PasskeyChallenge, UserPasskey
from models.users import SecurityEvent, User
from services.platform.passkey_service import PasskeyService
from services.platform.account_deletion_service import AccountDeletionService
from services.platform.user_session_service import UserSessionService


ORIGIN = 'https://finance.example.com'
RP_ID = 'finance.example.com'


@pytest.fixture(autouse=True)
def passkey_config(app, monkeypatch):
    monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', ORIGIN)
    monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', RP_ID)
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


class Authenticator:
    """Generate real ES256 WebAuthn responses without mocking the verifier."""

    def __init__(self):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = b'test-credential-' + self.private_key.public_key().public_numbers().x.to_bytes(32, 'big')
        numbers = self.private_key.public_key().public_numbers()
        self.public_key = cbor2.dumps({
            1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big'),
        })

    def response(self, options, *, register=False, origin=ORIGIN, rp_id=RP_ID, verified=True, count=0, user_id=None):
        client_data = json.dumps({
            'type': 'webauthn.create' if register else 'webauthn.get',
            'challenge': options['challenge'], 'origin': origin, 'crossOrigin': False,
        }).encode()
        flags = 0x01 | (0x04 if verified else 0) | (0x40 if register else 0)
        auth_data = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + count.to_bytes(4, 'big')
        response = {'clientDataJSON': bytes_to_base64url(client_data)}
        if register:
            auth_data += (
                bytes(16) + len(self.credential_id).to_bytes(2, 'big') + self.credential_id + self.public_key
            )
            response['attestationObject'] = bytes_to_base64url(cbor2.dumps({
                'fmt': 'none', 'attStmt': {}, 'authData': auth_data,
            }))
        else:
            response['authenticatorData'] = bytes_to_base64url(auth_data)
            response['signature'] = bytes_to_base64url(self.private_key.sign(
                auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()),
            ))
            response['userHandle'] = (
                bytes_to_base64url(f'familyhq-user-{user_id}'.encode()) if user_id else None
            )
        return {
            'id': bytes_to_base64url(self.credential_id), 'rawId': bytes_to_base64url(self.credential_id),
            'type': 'public-key', 'response': response,
        }


def password_login(client, user):
    return client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})


def logged_in(client):
    with client.session_transaction() as state:
        return '_user_id' in state


def register(client, user, authenticator=None):
    authenticator = authenticator or Authenticator()
    options = client.post('/account/security/passkeys/options', json={'name': 'My phone'})
    assert options.status_code == 200, options.data
    assert options.json['authenticatorSelection']['residentKey'] == 'required'
    assert options.json['authenticatorSelection']['userVerification'] == 'required'
    response = client.post('/account/security/passkeys/verify', json=authenticator.response(options.json, register=True))
    assert response.status_code == 200, response.data
    return authenticator


def sign_in(client, authenticator, **kwargs):
    options = client.post('/login/passkey/options', json={'remember': True})
    assert options.status_code == 200
    assert options.json['userVerification'] == 'required'
    return client.post('/login/passkey/verify', json=authenticator.response(options.json, **kwargs))


def logout(client):
    client.post('/logout')
    g.pop('_login_user', None)


def test_real_registration_and_passwordless_login(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    key = user.passkeys.one()
    assert key.name == 'My phone'
    assert key.public_key == authenticator.public_key
    assert key.sign_count == 0
    assert PasskeyChallenge.query.count() == 0
    logout(client)
    response = sign_in(client, authenticator, count=1, user_id=user.id)
    assert response.status_code == 200, response.data
    assert response.json['redirect'] == '/dashboard'
    assert logged_in(client)
    assert key.sign_count == 1
    assert key.last_used_at is not None
    record = user.sessions.order_by('id').all()[-1]
    assert record.authentication_method == 'passkey'
    assert record.remember
    assert 'remember_token' in ';'.join(response.headers.getlist('Set-Cookie'))
    assert SecurityEvent.query.filter_by(event_type='login_success').all()[-1].details == 'passkey, remembered'


@pytest.mark.parametrize('kind', ['origin', 'rp_id', 'verified', 'challenge', 'signature', 'handle'])
def test_authentication_rejects_invalid_proof(app, user, kind):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    options = client.post('/login/passkey/options', json={}).json
    kwargs = {
        'origin': {'origin': 'https://evil.example.com'},
        'rp_id': {'rp_id': 'evil.example.com'},
        'verified': {'verified': False},
        'handle': {'user_id': user.id + 100},
    }.get(kind, {})
    if kind == 'challenge':
        options['challenge'] = bytes_to_base64url(b'wrong-challenge')
    credential = authenticator.response(options, **kwargs)
    if kind == 'signature':
        credential['response']['signature'] = bytes_to_base64url(b'not-a-signature')
    response = client.post('/login/passkey/verify', json=credential)
    assert response.status_code == 400, response.data
    assert not logged_in(client)
    assert PasskeyChallenge.query.count() == 0
    assert user.passkeys.one().last_used_at is None


@pytest.mark.parametrize('kwargs', [
    {'origin': 'https://evil.example.com'}, {'rp_id': 'evil.example.com'}, {'verified': False},
])
def test_registration_requires_trusted_origin_rp_and_user_verification(app, user, kwargs):
    client = app.test_client()
    password_login(client, user)
    options = client.post('/account/security/passkeys/options', json={'name': 'Phone'}).json
    response = client.post('/account/security/passkeys/verify', json=Authenticator().response(options, register=True, **kwargs))
    assert response.status_code == 400
    assert user.passkeys.count() == 0
    assert PasskeyChallenge.query.count() == 0


def test_challenge_cannot_be_replayed_even_with_old_session_cookie(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    options = client.post('/login/passkey/options', json={}).json
    cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME']).value
    credential = authenticator.response(options)
    assert client.post('/login/passkey/verify', json=credential).status_code == 200
    other = app.test_client()
    other.set_cookie(app.config['SESSION_COOKIE_NAME'], cookie)
    g.pop('_login_user', None)
    assert other.post('/login/passkey/verify', json=credential).status_code == 400
    assert not logged_in(other)


def test_challenges_expire_and_are_bound_to_browser_and_purpose(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    options = client.post('/login/passkey/options', json={}).json
    credential = authenticator.response(options)
    assert app.test_client().post('/login/passkey/verify', json=credential).status_code == 400
    PasskeyChallenge.query.one().expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()
    assert client.post('/login/passkey/verify', json=credential).status_code == 400
    password_login(client, user)
    options = client.post('/account/security/passkeys/options', json={'name': 'Second'}).json
    # A registration challenge cannot confirm an authentication assertion.
    assert client.post('/account/confirm/passkey/verify', json=authenticator.response(options)).status_code == 400


def test_signature_counter_replay_rejected_and_synced_zero_counter_supported(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    for _ in range(2):
        assert sign_in(client, authenticator).status_code == 200
        logout(client)
    assert sign_in(client, authenticator, count=5).status_code == 200
    logout(client)
    assert sign_in(client, authenticator, count=5).status_code == 400
    assert not logged_in(client)


@pytest.mark.parametrize('state', ['inactive', 'locked', 'removed'])
def test_unavailable_account_or_credential_cannot_login(app, user, state):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    if state == 'inactive':
        user.is_active = False
    elif state == 'locked':
        user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
    else:
        db.session.delete(user.passkeys.one())
    db.session.commit()
    assert sign_in(client, authenticator).status_code == 400
    assert not logged_in(client)


def test_passkey_skips_totp_but_password_still_requires_it(app, user):
    from tests.test_two_factor import enable_two_factor
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    enable_two_factor(user)
    logout(client)
    assert password_login(client, user).headers['Location'].endswith('/login/two-factor')
    assert b'Use a passkey instead' in client.get('/login/two-factor').data
    assert not logged_in(client)
    assert sign_in(client, authenticator).status_code == 200
    with client.session_transaction() as state:
        assert '2fa_pending' not in state


def test_multiple_passkeys_exclusion_duplicate_and_removal(app, user):
    client = app.test_client()
    password_login(client, user)
    first = register(client, user)
    second = register(client, user)
    options = client.post('/account/security/passkeys/options', json={'name': 'Duplicate'}).json
    assert {key['id'] for key in options['excludeCredentials']} == {
        bytes_to_base64url(first.credential_id), bytes_to_base64url(second.credential_id),
    }
    assert client.post('/account/security/passkeys/verify', json=first.response(options, register=True)).status_code == 400
    assert user.passkeys.count() == 2
    key_id = user.passkeys.first().id
    response = client.post(f'/account/security/passkeys/{key_id}/remove')
    assert response.status_code == 302
    assert user.passkeys.count() == 1
    assert client.get('/account/security').status_code == 200
    logout(client)
    assert sign_in(client, first).status_code == 400
    assert sign_in(client, second).status_code == 200


def test_registration_and_removal_require_recent_auth_and_csrf(app, user, monkeypatch):
    client = app.test_client()
    assert client.post('/account/security/passkeys/options', json={'name': 'Phone'}).status_code == 302
    password_login(client, user)
    register(client, user)
    record = user.sessions.one()
    record.reauthenticated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    db.session.commit()
    g.pop('_login_user', None)
    response = client.post('/account/security/passkeys/options', json={'name': 'Second'})
    assert response.status_code == 302
    assert '/account/confirm' in response.headers['Location']
    assert client.post(f'/account/security/passkeys/{user.passkeys.one().id}/remove').status_code == 302
    assert user.passkeys.count() == 1
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    for endpoint in (
        '/login/passkey/options', '/login/passkey/verify',
        '/account/security/passkeys/options', '/account/security/passkeys/verify',
        '/account/confirm/passkey/options', '/account/confirm/passkey/verify',
        f'/account/security/passkeys/{user.passkeys.one().id}/remove',
    ):
        assert client.post(endpoint, json={}).status_code == 400


def test_reauth_is_account_bound_and_allows_passkey_sensitive_actions(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    other = User(email='other@example.com', name='Other', family_id=other_family.id, role='admin')
    other.set_password('TestPass1!')
    db.session.add(other)
    db.session.commit()
    second = app.test_client()
    g.pop('_login_user', None)
    password_login(second, other)
    other_authenticator = register(second, other)
    g.pop('_login_user', None)
    options = client.post('/account/confirm/passkey/options?next=/accounts/', json={}).json
    assert len(options['allowCredentials']) == 1
    assert client.post('/account/confirm/passkey/verify', json=other_authenticator.response(options)).status_code == 400
    key_id = other.passkeys.one().id
    assert client.post(f'/account/security/passkeys/{key_id}/remove').status_code == 302
    assert other.passkeys.count() == 1
    record = user.sessions.filter_by(revoked_at=None).one()
    record.reauthenticated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    db.session.commit()
    g.pop('_login_user', None)
    options = client.post('/account/confirm/passkey/options?next=/accounts/', json={}).json
    result = client.post('/account/confirm/passkey/verify', json=authenticator.response(options))
    assert result.status_code == 200
    assert result.json['redirect'] == '/accounts/'
    assert datetime.now(timezone.utc).replace(tzinfo=None) - record.reauthenticated_at < timedelta(seconds=10)


def test_site_admin_accepts_passkey_but_not_password_only_and_keeps_last_factor(app, user):
    user.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    password_login(client, user)
    assert client.get('/account/security').status_code == 200
    authenticator = register(client, user)
    assert client.get('/site-admin/').status_code == 200
    assert client.get('/site-admin/console/').status_code == 200
    response = client.post(f'/account/security/passkeys/{user.passkeys.one().id}/remove', follow_redirects=True)
    assert b'before removing your last passkey' in response.data
    assert user.passkeys.count() == 1
    logout(client)
    password_login(client, user)
    assert '/account/confirm' in client.get('/site-admin/').headers['Location']
    assert '/account/confirm' in client.get('/site-admin/console/').headers['Location']
    assert client.post('/account/security/passkeys/options', json={'name': 'Attacker'}).status_code == 400
    assert client.post(f'/account/security/passkeys/{user.passkeys.one().id}/remove').status_code == 302
    assert user.passkeys.count() == 1
    assert client.get('/account/security/two-factor/setup').status_code == 302
    assert user.totp_secret is None
    response = client.post('/account/confirm', data={'password': 'TestPass1!'})
    assert response.status_code == 200
    assert b'Use a registered passkey' in response.data
    logout(client)
    assert sign_in(client, authenticator).status_code == 200
    assert client.get('/site-admin/').status_code == 200


def test_server_reset_removes_passkeys_and_challenges_and_revokes_sessions(app, user):
    client = app.test_client()
    password_login(client, user)
    register(client, user)
    client.post('/account/security/passkeys/options', json={'name': 'Pending'})
    runner = app.test_cli_runner()
    result = runner.invoke(args=['passkeys', 'reset', user.email.upper()])
    assert result.exit_code == 0, result.output
    assert user.passkeys.count() == 0
    assert PasskeyChallenge.query.count() == 0
    assert all(record.revoked_at is not None for record in user.sessions.all())
    assert SecurityEvent.query.filter_by(event_type='passkeys_reset', user_id=user.id).count() == 1
    assert runner.invoke(args=['passkeys', 'reset', 'unknown@example.test']).exit_code == 1


def test_site_admin_can_disable_totp_with_passkey_and_keep_last_factor_protection(app, user):
    from tests.test_two_factor import enable_two_factor, totp_code
    from services.platform.two_factor_service import TwoFactorService
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    user.is_site_admin = True
    db.session.commit()
    enable_two_factor(user)
    TwoFactorService.disable(user, {'password': 'TestPass1!', 'code': totp_code(user, 1)})
    assert not user.two_factor_enabled
    assert user.passkeys.count() == 1
    assert client.get('/site-admin/').status_code == 200
    logout(client)
    assert sign_in(client, authenticator).status_code == 200


@pytest.mark.parametrize('name', ['', ' ', None, [], 'x' * 101])
def test_registration_validates_name(app, user, name):
    client = app.test_client()
    password_login(client, user)
    assert client.post('/account/security/passkeys/options', json={'name': name}).status_code == 400
    assert PasskeyChallenge.query.count() == 0


def test_registration_limit_and_malformed_user_handle(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    key = user.passkeys.one()
    for index in range(19):
        db.session.add(UserPasskey(
            user_id=user.id, credential_id=bytes_to_base64url(f'other-key-{index}'.encode()),
            public_key=key.public_key, sign_count=0, name=f'Key {index}', created_at=key.created_at,
        ))
    db.session.commit()
    assert client.post('/account/security/passkeys/options', json={'name': 'Too many'}).status_code == 400
    logout(client)
    options = client.post('/login/passkey/options', json={}).json
    credential = authenticator.response(options)
    credential['response']['userHandle'] = {'invalid': 'handle'}
    assert client.post('/login/passkey/verify', json=credential).status_code == 400


def test_unattached_user_login_goes_to_security_and_safe_next_is_preserved(app, user):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    options = client.post('/login/passkey/options?next=/accounts/', json={}).json
    assert client.post('/login/passkey/verify', json=authenticator.response(options)).json['redirect'] == '/accounts/'
    logout(client)
    user.family_id = None
    db.session.commit()
    assert sign_in(client, authenticator).json['redirect'] == '/account/security'


def test_passkey_changes_revoke_other_sessions(app, user):
    _, token = UserSessionService.create(user)
    client = app.test_client()
    password_login(client, user)
    register(client, user)
    assert UserSessionService.load_user(f'{user.id}:{token}') is None
    _, token = UserSessionService.create(user)
    client.post(f'/account/security/passkeys/{user.passkeys.one().id}/remove')
    assert UserSessionService.load_user(f'{user.id}:{token}') is None


@pytest.mark.parametrize('target', ['https://evil.example', '//evil.example', '/\\evil.example', '/%0devil'])
def test_login_redirect_is_local_only(app, user, target):
    client = app.test_client()
    password_login(client, user)
    authenticator = register(client, user)
    logout(client)
    options = client.post('/login/passkey/options', query_string={'next': target}, json={}).json
    response = client.post('/login/passkey/verify', json=authenticator.response(options))
    assert response.json['redirect'] == '/dashboard'


@pytest.mark.parametrize('body', [None, [], 'invalid', 12])
def test_options_reject_invalid_json(app, body):
    response = app.test_client().post('/login/passkey/options', json=body)
    assert response.status_code == 400
    assert response.is_json


@pytest.mark.parametrize('body', [{}, {'response': []}, {'id': []}, {'id': '???', 'response': {}}])
def test_verify_rejects_malformed_credentials(app, body):
    client = app.test_client()
    client.post('/login/passkey/options', json={})
    response = client.post('/login/passkey/verify', json=body)
    assert response.status_code == 400
    assert response.is_json


def test_passkey_routes_are_rate_limited(app):
    client = app.test_client()
    statuses = [client.post('/login/passkey/options', json={}).status_code for _ in range(11)]
    assert statuses == [200] * 10 + [429]


def test_configuration_never_trusts_request_host(app, monkeypatch):
    client = app.test_client()
    response = client.post('/login/passkey/options', json={}, headers={'Host': 'evil.example.com'})
    assert response.json['rpId'] == RP_ID
    for origin, rp_id in [
        ('', ''), ('http://finance.example.com', RP_ID),
        (ORIGIN, 'evil.example.com'), (ORIGIN + '/path', RP_ID),
        ('https://user:secret@finance.example.com', RP_ID),
    ]:
        monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', origin)
        monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', rp_id)
        with pytest.raises(ValueError):
            PasskeyService.configuration()
    monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', 'http://localhost:5000')
    monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', '')
    assert PasskeyService.configuration() == ('localhost', 'http://localhost:5000')


def test_ui_renders_and_credentials_not_in_admin(app, user):
    client = app.test_client()
    assert b'Sign in with a passkey' in client.get('/login').data
    password_login(client, user)
    register(client, user)
    assert b'My phone' in client.get('/account/security').data
    assert b'Confirm with a passkey' in client.get('/account/confirm').data
    user.is_site_admin = True
    db.session.commit()
    result = client.get('/site-admin/console/admin_user/')
    assert result.status_code == 200
    assert user.passkeys.one().credential_id.encode() not in result.data


def test_account_deletion_plan_includes_passkeys(app, user, monkeypatch):
    monkeypatch.setattr('services.platform.account_deletion_service.get_current_user_id', lambda: user.id)
    replacement = User(email='replacement@example.com', name='Replacement', family_id=user.family_id, role='admin')
    replacement.set_password('TestPass1!')
    db.session.add(replacement)
    db.session.commit()
    client = app.test_client()
    password_login(client, user)
    register(client, user)
    client.post('/account/security/passkeys/options', json={'name': 'Pending'})
    counts = AccountDeletionService.delete_account(user, {
        'confirmation': 'DELETE MY ACCOUNT', 'password': 'TestPass1!',
    })
    assert counts['user_passkeys'] == 1
    assert counts['passkey_challenges'] == 1
    assert UserPasskey.query.count() == PasskeyChallenge.query.count() == 0


def test_passkey_migration_round_trip_preserves_sessions():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    migration = importlib.import_module('migrations.versions.b9e4a7c1d6f2_add_passkeys')
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE user_sessions (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO user_sessions (id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT authentication_method FROM user_sessions')).scalar() == 'password'
            assert 'user_passkeys' in inspect(connection).get_table_names()
            migration.downgrade()
            assert connection.execute(text('SELECT id FROM user_sessions')).scalar() == 1
            assert 'user_passkeys' not in inspect(connection).get_table_names()
    engine.dispose()
