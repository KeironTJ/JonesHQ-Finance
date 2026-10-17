import re
from datetime import date, timedelta

import pytest
from flask import g

from extensions import db, limiter
from models.accounts import Account
from models.family import Family, FamilyInvite
from models.tax_settings import TaxSettings
from models.users import SecurityEvent, User, UserSession
from services.platform.user_session_service import _now
from tests.auth_helpers import login_client
from tests.test_account_security import enable_two_factor_admin, request


@pytest.fixture(autouse=True)
def reset_auth_state():
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)


@pytest.fixture
def admin_client(app, user):
    enable_two_factor_admin(user)
    client = app.test_client()
    login_client(client, user.id)
    return client


@pytest.fixture
def other_user(app):
    family_b = Family(name='Other household')
    db.session.add(family_b)
    db.session.flush()
    other = User(email='other@example.com', name='Other', family_id=family_b.id, role='admin')
    other.set_password('TestPass1!')
    db.session.add(other)
    db.session.commit()
    return other


def _csrf_token(html):
    # Flask-Admin SecureForm tokens look like "<timestamp>##<hmac>"
    for tag in re.findall(rb'<input[^>]*csrf_token[^>]*>', html):
        match = re.search(rb'value="([^"]+##[^"]+)"', tag)
        if match:
            return match.group(1).decode()
    raise AssertionError('No Flask-Admin CSRF token in admin page')


def _run_action(client, action, ids, token=None):
    if token is None:
        token = _csrf_token(request(client, 'get', '/admin/admin_user/').data)
    return request(client, 'post', '/admin/admin_user/action/', data={
        'action': action, 'rowid': [str(i) for i in ids], 'csrf_token': token,
    })


def test_household_financial_data_is_not_exposed(app, admin_client, other_user):
    db.session.add(Account(family_id=other_user.family_id, name='ZZSECRET acct', account_type='Joint',
                           balance=1, is_active=True))
    db.session.commit()

    for endpoint in ('admin_account', 'admin_transaction', 'admin_balance', 'admin_income',
                     'admin_pension', 'admin_settings', 'admin_taxsettings'):
        assert request(admin_client, 'get', f'/admin/{endpoint}/').status_code == 404, endpoint
    index = request(admin_client, 'get', '/admin/')
    assert index.status_code == 200
    assert b'Transactions' not in index.data
    assert b'ZZSECRET' not in index.data


def test_users_cannot_be_created_edited_or_deleted_directly(admin_client, other_user):
    for path in ('/admin/admin_user/new/', f'/admin/admin_user/edit/?id={other_user.id}'):
        assert request(admin_client, 'get', path).status_code in (302, 403, 404), path
    request(admin_client, 'post', '/admin/admin_user/delete/', data={'id': str(other_user.id)})
    assert db.session.get(User, other_user.id) is not None


def test_admin_actions_require_csrf_token(admin_client, other_user):
    _run_action(admin_client, 'deactivate', [other_user.id], token='forged')
    db.session.expire_all()
    assert db.session.get(User, other_user.id).is_active is True


def test_deactivate_signs_user_out_and_is_audited(admin_client, user, other_user):
    db.session.add(UserSession(user_id=other_user.id, token_hash='x' * 64,
                               created_at=_now(), last_seen_at=_now(),
                               expires_at=_now() + timedelta(days=1)))
    db.session.commit()

    response = _run_action(admin_client, 'deactivate', [other_user.id])

    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(User, other_user.id).is_active is False
    assert UserSession.query.filter_by(user_id=other_user.id, revoked_at=None).count() == 0
    event = SecurityEvent.query.filter_by(user_id=other_user.id, event_type='account_deactivated').one()
    assert event.details == f'by site admin {user.id}'

    _run_action(admin_client, 'reactivate', [other_user.id])
    db.session.expire_all()
    assert db.session.get(User, other_user.id).is_active is True


def test_admin_cannot_deactivate_themselves(admin_client, user):
    _run_action(admin_client, 'deactivate', [user.id])
    db.session.expire_all()
    assert db.session.get(User, user.id).is_active is True


def test_unlock_clears_lockout(admin_client, other_user):
    other_user.failed_login_attempts = 5
    other_user.locked_until = _now() + timedelta(minutes=30)
    db.session.commit()

    _run_action(admin_client, 'unlock', [other_user.id])

    db.session.expire_all()
    refreshed = db.session.get(User, other_user.id)
    assert refreshed.failed_login_attempts == 0 and refreshed.locked_until is None
    assert SecurityEvent.query.filter_by(user_id=other_user.id, event_type='account_unlocked').count() == 1


def test_family_invite_token_is_never_shown(admin_client, user):
    invite = FamilyInvite(family_id=user.family_id, member_name='Sam', created_by_id=user.id)
    db.session.add(invite)
    db.session.commit()

    for path in ('/admin/admin_familyinvite/', f'/admin/admin_familyinvite/details/?id={invite.id}'):
        response = request(admin_client, 'get', path)
        assert response.status_code == 200, path
        assert invite.token.encode() not in response.data, path


def test_tax_templates_view_only_shows_and_creates_global_rows(admin_client, user):
    household_row = TaxSettings(family_id=user.family_id, tax_year='HH-2026', effective_from=date(2026, 4, 6))
    template = TaxSettings(family_id=None, tax_year='GL-2026', effective_from=date(2026, 4, 6))
    db.session.add_all([household_row, template])
    db.session.commit()

    listing = request(admin_client, 'get', '/admin/admin_taxtemplate/')
    assert b'GL-2026' in listing.data and b'HH-2026' not in listing.data
    edit_household = request(admin_client, 'get', f'/admin/admin_taxtemplate/edit/?id={household_row.id}')
    assert edit_household.status_code == 302

    form_page = request(admin_client, 'get', '/admin/admin_taxtemplate/new/')
    response = request(admin_client, 'post', '/admin/admin_taxtemplate/new/', data={
        'csrf_token': _csrf_token(form_page.data),
        'tax_year': '2027-2028', 'effective_from': '2027-04-06',
        'personal_allowance': '12570', 'basic_rate_limit': '50270', 'higher_rate_limit': '125140',
        'basic_rate': '0.20', 'higher_rate': '0.40', 'additional_rate': '0.45',
        'ni_threshold': '12570', 'ni_upper_earnings': '50270',
        'ni_basic_rate': '0.08', 'ni_additional_rate': '0.02', 'is_active': 'y',
    })

    assert response.status_code == 302
    created = TaxSettings.query.filter_by(tax_year='2027-2028').one()
    assert created.family_id is None
