import pytest
from flask import g
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, limiter
from models.users import User
from services.platform.landing_service import LandingService
from tests.auth_helpers import login_client
from tests.test_passkeys import ORIGIN, RP_ID, register
from tests.test_two_factor import enable_two_factor, totp_code


@pytest.fixture(autouse=True)
def reset_login_state():
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


@pytest.mark.parametrize('workspace, destination', [('central', '/hub'), ('finance', '/dashboard')])
def test_workspace_is_personal_and_preserves_existing_preferences(app, family, user, workspace, destination):
    user.preferences = {
        'appearance.mode': 'auto', 'appearance.palette': 'purple',
        'dashboard.attention_days': 90,
    }
    member = User(
        family_id=family.id, email='member@example.com', name='Member',
        role='member', password_hash='unused', allowed_sections='["accounts"]',
    )
    db.session.add(member)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/preferences/workspace', data={
        'default_workspace': workspace, 'user_id': member.id,
    })
    assert response.location.endswith('/preferences#workspace-card')
    db.session.refresh(user)
    assert user.preferences == {
        'appearance.mode': 'auto', 'appearance.palette': 'purple',
        'dashboard.attention_days': 90, 'default_workspace': workspace,
    }
    assert not member.preferences
    html = client.get('/preferences').get_data(as_text=True)
    assert f'value="{workspace}" selected' in html
    assert client.get('/').location == destination
    assert client.get('/login').location == destination
    assert client.get('/login/two-factor').location == destination
    assert client.get('/hub').status_code == 200


@pytest.mark.parametrize('value', [None, '', 'family', '/dashboard', 'https://example.com'])
def test_invalid_workspace_does_not_change_any_preferences(app, user, value):
    user.preferences = {'default_workspace': 'finance', 'appearance.mode': 'dark'}
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    data = {} if value is None else {'default_workspace': value}
    response = client.post('/preferences/workspace', data=data, follow_redirects=True)
    assert response.status_code == 200
    assert b'Choose Central Hub or Finance' in response.data
    assert user.preferences == {'default_workspace': 'finance', 'appearance.mode': 'dark'}


def test_workspace_save_reports_database_failure(app, user, monkeypatch):
    client = app.test_client()
    login_client(client, user.id)

    def fail_commit():
        raise SQLAlchemyError('Test failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)
    response = client.post('/preferences/workspace', data={'default_workspace': 'finance'})
    assert response.status_code == 302
    assert not user.preferences
    html = client.get(response.location).get_data(as_text=True)
    assert 'Unable to save your default workspace. Please try again.' in html


def test_workspace_save_requires_login_and_csrf(app, user, monkeypatch):
    client = app.test_client()
    assert client.post('/preferences/workspace', data={'default_workspace': 'finance'}).status_code == 302
    login_client(client, user.id)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    assert client.post('/preferences/workspace', data={'default_workspace': 'finance'}).status_code == 400
    assert not user.preferences


@pytest.mark.parametrize('method', ['password', 'two_factor', 'passkey'])
@pytest.mark.parametrize('workspace, target, destination', [
    (None, None, '/hub'),
    ('central', None, '/hub'),
    ('finance', None, '/dashboard'),
    ('finance', '/hub', '/hub'),
    ('central', '/dashboard?year=2027#needs-attention', '/dashboard?year=2027#needs-attention'),
    ('finance', '/accounts/?view=all', '/accounts/?view=all'),
    ('finance', 'https://example.com', '/dashboard'),
    ('finance', '//example.com', '/dashboard'),
    ('finance', '/%5cexample.com', '/dashboard'),
])
def test_all_login_methods_use_same_workspace_and_deep_link_rules(
    app, user, monkeypatch, method, workspace, target, destination,
):
    if workspace:
        user.preferences = {'default_workspace': workspace}
        db.session.commit()
    client = app.test_client()
    query = {'next': target} if target is not None else {}
    if method == 'passkey':
        monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', ORIGIN)
        monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', RP_ID)
        login_client(client, user.id)
        authenticator = register(client, user)
        client.post('/logout')
        g.pop('_login_user', None)
        options = client.post('/login/passkey/options', query_string=query, json={})
        assert options.status_code == 200
        response = client.post('/login/passkey/verify', json=authenticator.response(options.json))
        assert response.status_code == 200
        assert response.json['redirect'] == destination
    else:
        if method == 'two_factor':
            enable_two_factor(user)
        response = client.post('/login', query_string=query, data={
            'email': user.email, 'password': 'TestPass1!',
        })
        if method == 'two_factor':
            assert response.location.endswith('/login/two-factor')
            response = client.post('/login/two-factor', data={'code': totp_code(user, 1)})
        assert response.status_code == 302
        assert response.location == destination


@pytest.mark.parametrize('method', ['password', 'two_factor', 'passkey'])
def test_detached_login_ignores_finance_default(app, user, monkeypatch, method):
    user.family_id = None
    user.preferences = {'default_workspace': 'finance'}
    db.session.commit()
    client = app.test_client()
    if method == 'passkey':
        monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', ORIGIN)
        monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', RP_ID)
        login_client(client, user.id)
        authenticator = register(client, user)
        client.post('/logout')
        g.pop('_login_user', None)
        options = client.post('/login/passkey/options', json={}).json
        response = client.post('/login/passkey/verify', json=authenticator.response(options))
        assert response.json['redirect'] == '/account/security'
    else:
        if method == 'two_factor':
            enable_two_factor(user)
        response = client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})
        if method == 'two_factor':
            response = client.post('/login/two-factor', data={'code': totp_code(user, 1)})
        assert response.location == '/account/security'


def test_member_default_workspace_does_not_grant_section_access(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    assert client.post('/preferences/workspace', data={'default_workspace': 'finance'}).status_code == 302
    assert client.get('/').location == '/dashboard'
    assert client.get('/income').status_code == 403
    assert client.get('/settings').status_code == 403


@pytest.mark.parametrize('target', [None, '/dashboard?year=2027', '/hub#workspaces', '/'])
def test_detached_default_destinations_use_security(app, user, target):
    user.family_id = None
    db.session.commit()
    with app.test_request_context():
        assert LandingService.resolve(user, target) == '/account/security'
