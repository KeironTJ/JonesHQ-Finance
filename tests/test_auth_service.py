from datetime import datetime, timedelta, timezone

import pytest

from extensions import db
from models.family import Family
from models.users import SecurityEvent, User
from services.platform.auth_service import AuthService


def test_authenticate_normalizes_email_and_clears_failed_attempts(app, user):
    user.failed_login_attempts = 2
    user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    db.session.commit()

    authenticated = AuthService.authenticate({
        'email': ' ADMIN@EXAMPLE.COM ',
        'password': 'TestPass1!',
    })

    assert authenticated is user
    assert user.failed_login_attempts == 0
    assert user.locked_until is None
    assert user.last_login is not None


def test_authenticate_records_failed_attempt_and_lock_event(app, user):
    user.failed_login_attempts = app.config['MAX_LOGIN_ATTEMPTS'] - 1
    db.session.commit()

    with pytest.raises(ValueError, match='Invalid email or password'):
        AuthService.authenticate({'email': user.email, 'password': 'WrongPass1!'})

    assert user.failed_login_attempts == app.config['MAX_LOGIN_ATTEMPTS']
    assert user.is_locked()
    assert [event.event_type for event in SecurityEvent.query.order_by(SecurityEvent.id)] == [
        'login_failed',
        'account_locked',
    ]


def test_authenticate_rejects_unknown_user(app):
    with pytest.raises(ValueError, match='Invalid email or password'):
        AuthService.authenticate({'email': 'missing@example.com', 'password': 'WrongPass1!'})

    assert User.query.count() == 0
    assert SecurityEvent.query.count() == 0


def test_register_user_creates_family_and_admin(app):
    family, user = AuthService.register_user(
        'Jones Household',
        'ADMIN@EXAMPLE.COM',
        'Admin User',
        'TestPass1!',
    )

    assert family.name == 'Jones Household'
    assert user.family_id == family.id
    assert user.role == 'admin'
    assert user.email == 'admin@example.com'
    assert user.check_password('TestPass1!') is True
    assert db.session.get(Family, family.id) is family
    assert db.session.get(User, user.id) is user
