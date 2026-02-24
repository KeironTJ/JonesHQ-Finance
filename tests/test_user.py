"""
Tests for the User model: password hashing, section permissions, and login lockout.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from extensions import db
from models.users import User
from models.family import Family


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def member_user(app, family):
    """A 'member' role user with no allowed_sections set yet."""
    u = User(
        email='member@example.com',
        name='Member User',
        family_id=family.id,
        role='member',
    )
    u.set_password('TestPass1!')
    db.session.add(u)
    db.session.commit()
    return u


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_correct_password_accepted(self, app, user):
        assert user.check_password('TestPass1!') is True

    def test_wrong_password_rejected(self, app, user):
        assert user.check_password('WrongPass99!') is False

    def test_password_is_hashed(self, app, user):
        assert user.password_hash != 'TestPass1!', \
            "password_hash must store a hash, not the plain-text password"


# ---------------------------------------------------------------------------
# Section-level permissions
# ---------------------------------------------------------------------------

class TestSectionPermissions:
    def test_admin_can_access_any_section(self, app, user):
        """Admin role bypasses all section restrictions."""
        assert user.is_admin is True
        for section in ('transactions', 'income', 'settings', 'family', 'credit_cards'):
            assert user.can_access_section(section) is True, \
                f"Admin should be able to access '{section}'"

    def test_admin_get_allowed_sections_returns_none(self, app, user):
        """Admin get_allowed_sections() returns None (= unrestricted)."""
        assert user.get_allowed_sections() is None

    def test_member_can_access_listed_section(self, app, member_user):
        member_user.set_allowed_sections(['transactions', 'accounts'])
        db.session.commit()

        assert member_user.can_access_section('transactions') is True
        assert member_user.can_access_section('accounts') is True

    def test_member_cannot_access_unlisted_section(self, app, member_user):
        member_user.set_allowed_sections(['transactions'])
        db.session.commit()

        assert member_user.can_access_section('income') is False

    def test_member_with_no_sections_cannot_access_anything(self, app, member_user):
        """member_user fixture has no allowed_sections set."""
        assert member_user.can_access_section('transactions') is False
        assert member_user.can_access_section('accounts') is False

    def test_set_allowed_sections_deduplicates_and_sorts(self, app, member_user):
        member_user.set_allowed_sections(['income', 'accounts', 'income'])
        db.session.commit()

        stored = json.loads(member_user.allowed_sections)
        assert stored == sorted(set(['income', 'accounts']))


# ---------------------------------------------------------------------------
# Login lockout
# ---------------------------------------------------------------------------

class TestLoginLockout:
    def test_account_not_locked_initially(self, app, user):
        assert user.is_locked() is False

    def test_lockout_applied_after_max_attempts(self, app, user):
        max_attempts = app.config['MAX_LOGIN_ATTEMPTS']
        for _ in range(max_attempts):
            user.record_failed_login()

        assert user.is_locked() is True
        assert user.locked_until is not None

    def test_failed_attempts_below_threshold_do_not_lock(self, app, user):
        max_attempts = app.config['MAX_LOGIN_ATTEMPTS']
        for _ in range(max_attempts - 1):
            user.record_failed_login()

        assert user.is_locked() is False

    def test_reset_clears_lockout(self, app, user):
        max_attempts = app.config['MAX_LOGIN_ATTEMPTS']
        for _ in range(max_attempts):
            user.record_failed_login()

        assert user.is_locked() is True

        user.reset_failed_logins()

        assert user.is_locked() is False
        assert user.failed_login_attempts == 0
        assert user.locked_until is None

    def test_expired_lockout_is_not_locked(self, app, user):
        """A locked_until timestamp in the past should not count as locked."""
        user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.session.commit()

        assert user.is_locked() is False
