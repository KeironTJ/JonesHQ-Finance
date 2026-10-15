from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from flask import g
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from models.accounts import Account
from models.categories import Category
from models.family import Family
from models.income import Income
from models.loan_term_changes import LoanTermChange
from models.loans import Loan
from models.plans import Plan, PlanItem
from models.transactions import Transaction
from models.users import SecurityEvent, User, UserSession
from services.platform.data_export_service import DataExportService, EXPORTS
from services.platform.user_session_service import _now
from tests.auth_helpers import login_client


@pytest.fixture(autouse=True)
def clear_state(app):
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


@pytest.fixture
def export_records(user, family):
    other_family = Family(name='Foreign household')
    member = User(email='private@example.com', name='Other member',
                  family_id=family.id, role='member')
    member.set_password('PrivatePass1!')
    db.session.add_all([other_family, member])
    db.session.flush()
    accounts = [
        Account(family_id=family.id, name='Shared account', account_type='Current',
                balance=Decimal('123.45')),
        Account(family_id=family.id, name='Own account', account_type='Current',
                owner_id=user.id),
        Account(family_id=family.id, name='Private account', account_type='Current',
                owner_id=member.id),
        Account(family_id=other_family.id, name='Foreign account', account_type='Current'),
    ]
    db.session.add_all(accounts)
    db.session.flush()
    for account in accounts:
        category = Category(family_id=account.family_id, name='General',
                            category_type='expense', head_budget='Household', sub_budget='Other')
        db.session.add(category)
        db.session.flush()
        db.session.add(Transaction(
            family_id=account.family_id, account_id=account.id,
            category_id=category.id,
            amount=Decimal('12.34'), transaction_date=date(2026, 1, 5),
            description=account.name + ' transaction'))
    for owner_id in (None, user.id, member.id):
        plan = Plan(family_id=family.id, title=f'Plan {owner_id}', owner_id=owner_id)
        loan = Loan(
            family_id=family.id, name=f'Loan {owner_id}', owner_id=owner_id,
            loan_value=100, principal=100, current_balance=100,
            annual_apr=0, monthly_apr=0, monthly_payment=20,
            start_date=date(2026, 1, 5), term_months=5)
        db.session.add_all([plan, loan])
        db.session.flush()
        db.session.add(PlanItem(family_id=family.id, plan_id=plan.id, title='Item'))
        db.session.add(LoanTermChange(
            family_id=family.id, loan_id=loan.id, effective_date=date(2026, 1, 5),
            new_monthly_payment=Decimal('20')))
    db.session.commit()
    return accounts


def download(app, user):
    client = app.test_client()
    login_client(client, user.id)
    return client, client.post('/account/security/export')


def test_export_shape_precision_dates_and_secret_exclusion(app, user, export_records):
    _, response = download(app, user)
    assert response.status_code == 200
    assert response.mimetype == 'application/json'
    assert response.headers['Content-Disposition'] == 'attachment; filename="family-hq-export.json"'
    assert response.headers['Cache-Control'] == 'no-store'
    payload = response.get_json()
    assert payload['format_version'] == 1
    assert payload['profile']['email'] == user.email
    assert payload['data']['accounts'][0]['balance'] == '123.45'
    assert payload['data']['transactions'][0]['amount'] == '12.34'
    assert payload['data']['transactions'][0]['transaction_date'] == '2026-01-05'
    assert payload['excluded']
    assert 'private@example.com' not in response.get_data(as_text=True)
    forbidden = {'password_hash', 'totp_secret', 'totp_last_step', 'code_hash', 'token', 'token_hash'}
    for rows in payload['data'].values():
        for row in rows:
            assert forbidden.isdisjoint(row)
    assert forbidden.isdisjoint(payload['profile'])
    assert SecurityEvent.query.filter_by(user_id=user.id, event_type='data_exported').count() == 1


def test_export_keeps_private_and_foreign_records_out_even_for_admin(app, user, export_records):
    _, response = download(app, user)
    data = response.get_json()['data']
    assert [row['name'] for row in data['accounts']] == ['Shared account', 'Own account']
    assert len(data['transactions']) == 2
    assert len(data['plans']) == len(data['plan_items']) == 2
    assert len(data['loans']) == len(data['loan_term_changes']) == 2
    assert 'Private account' not in response.get_data(as_text=True)
    assert 'Foreign account' not in response.get_data(as_text=True)


def test_site_admin_export_still_has_normal_record_visibility(app, user, export_records):
    user.is_site_admin = True
    user.totp_secret = 'JBSWY3DPEHPK3PXP'
    user.totp_enabled_at = _now()
    db.session.commit()
    _, response = download(app, user)
    assert [row['name'] for row in response.get_json()['data']['accounts']] == [
        'Shared account', 'Own account',
    ]


def test_export_section_permissions_cannot_be_overridden_by_request(app, user, export_records):
    user.role = 'member'
    user.set_allowed_sections(['accounts'])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/account/security/export?section=transactions&family_id=999',
                           data={'sections': 'all', 'include_private': 'true'})
    payload = response.get_json()
    assert payload['sections'] == ['accounts']
    assert set(payload['data']) == {'accounts', 'balances'}
    assert len(payload['data']['accounts']) == 2


def test_export_member_with_no_sections_gets_only_own_profile(app, user):
    user.role = 'member'
    user.set_allowed_sections([])
    db.session.commit()
    _, response = download(app, user)
    assert response.get_json()['data'] == {}
    assert response.get_json()['profile']['id'] == user.id


def test_export_shared_account_transaction_does_not_inherit_income_privacy(app, user, family, export_records):
    member = User.query.filter_by(email='private@example.com').one()
    transaction = Transaction.query.filter_by(account_id=export_records[0].id).one()
    db.session.add(Income(
        family_id=family.id, person='Private salary', pay_date=date(2026, 1, 5),
        gross_annual_income=Decimal('10000'), gross_monthly_income=Decimal('833.33'), take_home=800,
        owner_id=member.id, transaction_id=transaction.id))
    db.session.commit()
    _, response = download(app, user)
    data = response.get_json()['data']
    assert data['income'] == []
    assert transaction.id in [row['id'] for row in data['transactions']]


def test_export_requires_login_and_post(app):
    client = app.test_client()
    assert client.post('/account/security/export').status_code == 302
    assert client.get('/account/security/export').status_code == 405


def test_export_requires_recent_password(app, user):
    client = app.test_client()
    login_client(client, user.id)
    UserSession.query.filter_by(user_id=user.id).update({
        'reauthenticated_at': _now() - timedelta(hours=1),
    })
    db.session.commit()
    g.pop('_login_user', None)
    response = client.post('/account/security/export')
    assert response.status_code == 302
    assert '/account/confirm' in response.headers['Location']
    assert SecurityEvent.query.filter_by(event_type='data_exported').count() == 0


def test_export_rate_limit_is_per_user(app, user):
    client = app.test_client()
    login_client(client, user.id)
    assert client.post('/account/security/export').status_code == 200
    g.pop('_login_user', None)
    login_client(client, user.id)
    assert client.post('/account/security/export').status_code == 200
    assert client.post('/account/security/export').status_code == 429


def test_export_requires_csrf(app, user, monkeypatch):
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    client = app.test_client()
    login_client(client, user.id)
    assert client.post('/account/security/export').status_code == 400
    assert SecurityEvent.query.filter_by(event_type='data_exported').count() == 0


def test_export_rejects_removed_member(app, user):
    client = app.test_client()
    login_client(client, user.id)
    user.family_id = None
    db.session.commit()
    response = client.post('/account/security/export')
    assert response.status_code == 302
    assert SecurityEvent.query.filter_by(event_type='data_exported').count() == 0


def test_export_database_failure_does_not_return_partial_download(app, user, monkeypatch):
    monkeypatch.setattr(DataExportService, 'create', Mock(
        side_effect=OperationalError('SELECT', {}, Exception('database unavailable'))))
    _, response = download(app, user)
    assert response.status_code == 302
    assert 'Content-Disposition' not in response.headers
    assert SecurityEvent.query.filter_by(event_type='data_exported').count() == 0


def test_account_security_explains_export_and_provides_post_form(app, user):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/account/security')
    assert b'action="/account/security/export"' in response.data
    assert b'not a database backup' in response.data
    assert b'two downloads per hour' in response.data


def test_allowlist_fields_exist_and_omit_authentication_models(app):
    for models in EXPORTS.values():
        for model, fields in models:
            for field in fields.split():
                assert field in model.__table__.columns, (model, field)
            assert model.__tablename__ not in {
                'users', 'user_sessions', 'user_recovery_codes', 'family_invites',
                'household_invites', 'settings', 'security_events',
            }


def test_export_service_fails_closed_without_current_user(app, user, monkeypatch):
    monkeypatch.setattr('services.platform.data_export_service.get_current_user_id', lambda: None)
    with pytest.raises(ValueError, match='household membership'):
        DataExportService.create(user)
