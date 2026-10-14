from datetime import datetime, timedelta, timezone

import pytest
from flask import g

from extensions import db, limiter
from models.family import Family, HouseholdInvite
from models.users import User
from services.platform.auth_service import AuthService
from services.platform.household_invite_service import HouseholdInviteService


PASSWORD = 'StrongPass1!'


@pytest.fixture(autouse=True)
def reset_auth_state(app):
    g.pop('_login_user', None)
    limiter.reset()
    app.config['ALLOW_OPEN_REGISTRATION'] = False
    yield
    g.pop('_login_user', None)
    limiter.reset()
    app.config['ALLOW_OPEN_REGISTRATION'] = False


def registration_data(token='', **overrides):
    data = {
        'invite_token': token,
        'household_name': 'New Household',
        'name': 'New Admin',
        'email': 'new@example.com',
        'password': PASSWORD,
        'confirm_password': PASSWORD,
    }
    data.update(overrides)
    return data


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_register_page_without_invite_shows_invitation_notice(app):
    response = app.test_client().get('/register')
    assert response.status_code == 200
    assert b'by invitation only' in response.data
    assert b'name="password"' not in response.data


def test_register_post_without_invite_creates_nothing(app):
    response = app.test_client().post('/register', data=registration_data())
    assert response.status_code == 200
    assert User.query.count() == 0
    assert Family.query.count() == 0


def test_valid_invite_registers_household_once(app):
    invite, token = HouseholdInviteService.create_invite({})
    client = app.test_client()

    page = client.get(f'/register?invite={token}')
    assert page.status_code == 200
    assert b'name="password"' in page.data
    assert token.encode() in page.data

    response = client.post('/register', data=registration_data(token))
    assert response.status_code == 302
    created = User.query.filter_by(email='new@example.com').one()
    db.session.refresh(invite)
    assert invite.status == 'used'
    assert invite.used_by_id == created.id

    g.pop('_login_user', None)
    second = app.test_client().post('/register', data=registration_data(token, email='other@example.com'))
    assert second.status_code == 200
    assert User.query.filter_by(email='other@example.com').first() is None


def test_only_token_hash_is_stored(app):
    invite, token = HouseholdInviteService.create_invite({})
    assert invite.token_hash == HouseholdInvite.hash_token(token)
    assert token not in invite.token_hash


@pytest.mark.parametrize('state', ['expired', 'revoked'])
def test_expired_or_revoked_invite_is_rejected(app, state):
    invite, token = HouseholdInviteService.create_invite({})
    if state == 'expired':
        invite.expires_at = _now() - timedelta(minutes=1)
        db.session.commit()
    else:
        HouseholdInviteService.revoke_invite(invite.id)

    with pytest.raises(ValueError, match='invalid, has expired or has already been used'):
        AuthService.register_household(registration_data(token))
    assert User.query.count() == 0


def test_email_restricted_invite_rejects_other_email(app):
    _, token = HouseholdInviteService.create_invite({'email': 'Invited@Example.com'})
    with pytest.raises(ValueError, match='different email'):
        AuthService.register_household(registration_data(token, email='someone@example.com'))

    _, user = AuthService.register_household(registration_data(token, email='invited@example.com'))
    assert user.email == 'invited@example.com'


def test_failed_registration_does_not_consume_invite(app, user):
    invite, token = HouseholdInviteService.create_invite({})
    with pytest.raises(ValueError, match='already exists'):
        AuthService.register_household(registration_data(token, email=user.email))
    with pytest.raises(ValueError, match='Password must contain'):
        AuthService.register_household(registration_data(token, password='weak'))
    db.session.rollback()
    db.session.refresh(invite)
    assert invite.status == 'active'


def test_claim_cannot_succeed_twice(app):
    invite, _ = HouseholdInviteService.create_invite({})
    HouseholdInviteService.claim_invite(invite)
    with pytest.raises(ValueError):
        HouseholdInviteService.claim_invite(invite)


def test_open_registration_allows_signup_without_invite(app):
    app.config['ALLOW_OPEN_REGISTRATION'] = True
    _, user = AuthService.register_household(registration_data())
    assert user.role == 'admin'


@pytest.mark.parametrize('data, message', [
    ({'days': 0}, 'between 1 and 30'),
    ({'days': 31}, 'between 1 and 30'),
    ({'days': 'x'}, 'whole number'),
    ({'email': 'not-an-email'}, 'valid email'),
])
def test_create_invite_validates_input(app, data, message):
    with pytest.raises(ValueError, match=message):
        HouseholdInviteService.create_invite(data)


def _login(app, user):
    client = app.test_client()
    client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})
    return client


def test_invite_admin_page_requires_site_admin(app, user):
    client = _login(app, user)
    assert client.get('/site-admin/household-invites').status_code == 403
    assert client.post('/site-admin/household-invites', data={'days': 7}).status_code == 403
    assert HouseholdInvite.query.count() == 0


def test_site_admin_can_create_and_revoke_invite(app, user):
    user.is_site_admin = True
    db.session.commit()
    client = _login(app, user)

    response = client.post('/site-admin/household-invites', data={'email': '', 'note': 'Smiths', 'days': 3})
    assert response.status_code == 200
    assert b'/register?invite=' in response.data
    invite = HouseholdInvite.query.one()
    assert invite.note == 'Smiths'
    assert invite.created_by_id == user.id

    response = client.post(f'/site-admin/household-invites/{invite.id}/revoke')
    assert response.status_code == 302
    db.session.refresh(invite)
    assert invite.status == 'revoked'


def test_cli_creates_invite_link(app):
    result = app.test_cli_runner().invoke(args=[
        'household-invite', 'create', '--note', 'CLI', '--base-url', 'https://finance.example.com/',
    ])
    assert result.exit_code == 0, result.output
    assert 'https://finance.example.com/register?invite=' in result.output
    assert HouseholdInvite.query.one().note == 'CLI'
