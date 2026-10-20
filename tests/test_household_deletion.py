from datetime import timedelta
from unittest.mock import Mock

import pytest
from flask import g
from sqlalchemy import Column, ForeignKey, Integer, Table, select, text
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from models import (
    Account, Budget, ChildcareRecord, ExpenseReimbursementGroup, Family, FamilyAssignmentLabel,
    FamilyInvite, HouseholdInvite, Mortgage, MortgagePayment, MortgageProduct, MortgageSnapshot,
    NetWorth, PlannedTransaction, Property, PropertyValuationSnapshot, SecurityEvent, Settings,
    Subscription, SubscriptionPriceChange, TaxSettings, Transaction, User, UserRecoveryCode,
    UserSession, Vendor, VendorType,
)
from models.childcare import Child, ChildActivityType, DailyChildcareActivity, MonthlyChildcareSummary
from services.household.household_deletion_service import HOUSEHOLD_TABLES, HouseholdDeletionService
from services.platform.user_session_service import _now
from tests.auth_helpers import login_client
from tests.test_account_deletion import TODAY, add, make_domains


VALID_DATA = {'password': 'TestPass1!', 'confirmation': 'DELETE THIS HOUSEHOLD'}


@pytest.fixture(autouse=True)
def isolate_state(app, family, monkeypatch):
    monkeypatch.setitem(VALID_DATA, 'family_id', str(family.id))
    g.pop('_login_user', None)
    limiter.reset()
    db.session.rollback()
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
    yield
    g.pop('_login_user', None)
    limiter.reset()
    db.session.rollback()
    db.session.execute(text('PRAGMA foreign_keys=OFF'))


def extended_domains(owner, family_id, prefix):
    data = make_domains(owner, family_id, prefix)
    account, category, transaction = (data[key] for key in ('account', 'category', 'transaction'))
    subscription = db.session.execute(select(Subscription).where(
        Subscription.family_id == family_id, Subscription.account_id == account.id,
    )).scalar_one()
    add(SubscriptionPriceChange, family_id=family_id, subscription_id=subscription.id,
        amount=-12, effective_date=TODAY, note='Annual increase')
    vendor_type = add(VendorType, family_id=family_id, name=prefix)
    vendor = add(Vendor, family_id=family_id, name=prefix, vendor_type_id=vendor_type.id,
                 default_category_id=category.id)
    child = add(Child, family_id=family_id, name=prefix, default_account_id=account.id,
                category_id=category.id, vendor_id=vendor.id)
    activity = add(ChildActivityType, family_id=family_id, child_id=child.id, name=prefix, cost=5)
    prop = add(Property, family_id=family_id, address=prefix)
    product = add(MortgageProduct, family_id=family_id, property_id=prop.id, account_id=account.id,
                  vendor_id=vendor.id, category_id=category.id, lender=prefix, product_name=prefix,
                  start_date=TODAY, end_date=TODAY, term_months=12, initial_balance=100,
                  current_balance=100, annual_rate=1, monthly_payment=10)
    mortgage = add(Mortgage, family_id=family_id, property_address=prefix, principal=100,
                   current_balance=100, interest_rate=1, fixed_payment=10, start_date=TODAY, term_years=1)
    for model, values in (
        (DailyChildcareActivity, dict(child_id=child.id, activity_type_id=activity.id, date=TODAY)),
        (MonthlyChildcareSummary, dict(child_id=child.id, year_month='2026-10', total_cost=5,
                                      transaction_id=transaction.id, account_id=account.id)),
        (ChildcareRecord, dict(date=TODAY, child_name=prefix, cost=5)),
        (MortgageSnapshot, dict(mortgage_product_id=product.id, transaction_id=transaction.id,
                               date=TODAY, balance=100, monthly_payment=10, interest_charge=1, principal_paid=9)),
        (MortgagePayment, dict(mortgage_id=mortgage.id, date=TODAY, mortgage_balance=100,
                              fixed_payment=10, interest_charge=1, equity_paid=9)),
        (PropertyValuationSnapshot, dict(property_id=prop.id, valuation_date=TODAY, value=200)),
        (NetWorth, dict(date=TODAY, total_assets=200, total_liabilities=100, net_worth=100)),
        (Settings, dict(key=prefix, value='value')),
        (TaxSettings, dict(tax_year=f'{prefix}-2026', effective_from=TODAY, effective_to=TODAY)),
        (Budget, dict(category_id=category.id, amount=100, period_start=TODAY, period_end=TODAY)),
        (PlannedTransaction, dict(category_id=category.id, amount=-5, planned_date=TODAY)),
        (FamilyAssignmentLabel, dict(name=prefix)),
        (ExpenseReimbursementGroup, dict(name=prefix, recurring_income_id=data['recurring'].id)),
        (FamilyInvite, dict(member_name=prefix, created_by_id=owner.id)),
    ):
        add(model, family_id=family_id, **values)
    return data


@pytest.fixture
def graph(user, family):
    member = add(User, family_id=family.id, email='member@example.com', name='Member',
                 role='member', password_hash=user.password_hash, is_active=False,
                 member_name='Old display name', allowed_sections='["accounts"]')
    former_member = add(User, family_id=None, email='former@example.com', name='Former',
                        role='member', password_hash=user.password_hash)
    other_family = add(Family, name='Foreign')
    foreign_user = add(User, family_id=other_family.id, email='foreign@example.com', name='Foreign',
                       role='admin', password_hash=user.password_hash)
    own = extended_domains(user, family.id, 'Own')
    private = make_domains(member, family.id, 'Member')
    shared = make_domains(None, family.id, 'Shared')
    former = make_domains(former_member, family.id, 'Former')
    foreign = extended_domains(foreign_user, other_family.id, 'Foreign')
    user.default_account_id = own['account'].id
    member.default_account_id = private['account'].id
    own['transaction'].linked_transaction_id = private['transaction'].id
    private['transaction'].linked_transaction_id = own['transaction'].id
    own['expense'].bank_transaction_id = private['transaction'].id
    own['income'].transaction_id = own['transaction'].id
    add(SecurityEvent, user_id=user.id, family_id=family.id, event_type='login_success')
    add(UserRecoveryCode, user_id=member.id, code_hash='a' * 64)
    add(HouseholdInvite, created_by_id=user.id, token_hash='b' * 64,
        expires_at=_now() + timedelta(days=1))
    # Global templates must never be swept up with a household's settings.
    add(Settings, family_id=None, key='global', value='keep')
    db.session.commit()
    return member, former_member, foreign_user, own, private, shared, former, foreign


def sign_in(app, user):
    client = app.test_client()
    login_client(client, user.id)
    return client


def test_deletes_every_household_table_but_retains_accounts_and_other_families(app, user, family, graph):
    member, former_member, foreign_user, *_ = graph
    family_id, member_ids = family.id, [user.id, member.id]
    credential_hashes = {u.id: u.password_hash for u in (user, member)}
    other_client = sign_in(app, member)
    foreign_client = sign_in(app, foreign_user)
    former_client = sign_in(app, former_member)
    client = sign_in(app, user)
    foreign_rows = {
        name: db.session.execute(select(db.metadata.tables[name]).where(
            db.metadata.tables[name].c.family_id == foreign_user.family_id)).mappings().all()
        for name in HOUSEHOLD_TABLES
    }
    # Every reviewed table has a real record, not merely a passing empty-table check.
    for name in HOUSEHOLD_TABLES:
        assert db.session.execute(select(db.metadata.tables[name].c.id).where(
            db.metadata.tables[name].c.family_id == family_id)).first(), name
    response = client.post('/family/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert db.session.execute(select(Family.id).where(Family.id == family_id)).first() is None
    for name in HOUSEHOLD_TABLES:
        table = db.metadata.tables[name]
        assert not db.session.execute(select(table.c.id).where(table.c.family_id == family_id)).first()
        assert db.session.execute(select(table).where(
            table.c.family_id == foreign_user.family_id)).mappings().all() == foreign_rows[name]
    for member_id in member_ids:
        kept = db.session.get(User, member_id)
        assert kept.family_id is None
        assert kept.role == 'member'
        assert kept.allowed_sections is kept.member_name is kept.default_account_id is None
        assert kept.password_hash == credential_hashes[member_id]
        assert db.session.execute(select(UserSession.id).where(
            UserSession.user_id == member_id, UserSession.revoked_at.is_(None))).first() is None
        assert SecurityEvent.query.filter_by(user_id=member_id, event_type='household_deleted').one().family_id is None
    assert UserRecoveryCode.query.filter_by(user_id=member.id).count() == 1
    assert SecurityEvent.query.filter_by(event_type='login_success').one().family_id is None
    assert HouseholdInvite.query.one().revoked_at is None
    assert Settings.query.filter_by(key='global', family_id=None).one().value == 'keep'
    assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []
    for signed_out in (client, other_client):
        g.pop('_login_user', None)
        assert signed_out.get('/account/security').status_code == 302
    for retained in (foreign_client, former_client):
        g.pop('_login_user', None)
        assert retained.get('/account/security').status_code == 200


def test_preview_is_read_only_and_warns_about_every_members_private_data(app, user, family, graph):
    client = sign_in(app, user)
    response = client.get('/family/delete')
    assert response.status_code == 200
    assert b'Member (member@example.com)' in response.data
    assert b'Former' not in response.data  # no former-member identities in the member list
    assert b'other members or former members' in response.data
    assert b'DELETE THIS HOUSEHOLD' in response.data
    assert b'export does not include other members' in response.data
    assert db.session.get(Family, family.id) is not None
    assert UserSession.query.filter_by(user_id=user.id, revoked_at=None).count() == 1


@pytest.mark.parametrize('data,message', [
    (dict(VALID_DATA, password='wrong'), b'password was not correct'),
    (dict(VALID_DATA, confirmation='delete this household'), b'Type DELETE THIS HOUSEHOLD exactly'),
    (dict(VALID_DATA, password=''), b'This field is required'),
])
def test_password_and_phrase_are_required(app, user, family, data, message):
    response = sign_in(app, user).post('/family/delete', data=dict(data, family_id=family.id))
    assert response.status_code == 200
    assert message in response.data
    assert db.session.get(Family, family.id) is not None


def test_member_and_detached_user_cannot_delete_household(app, user, family):
    user.role = 'member'
    db.session.commit()
    client = sign_in(app, user)
    assert client.post('/family/delete', data=VALID_DATA).status_code == 403
    user.family_id = None
    user.role = 'admin'
    db.session.commit()
    g.pop('_login_user', None)
    assert client.post('/family/delete', data=VALID_DATA).status_code == 403
    assert db.session.get(Family, family.id) is not None


def test_requires_login_recent_auth_and_csrf(app, user, monkeypatch):
    assert app.test_client().post('/family/delete', data=VALID_DATA).status_code == 302
    client = sign_in(app, user)
    UserSession.query.filter_by(user_id=user.id).update({
        'reauthenticated_at': _now() - timedelta(hours=1)})
    db.session.commit()
    g.pop('_login_user', None)
    assert '/account/confirm' in client.post('/family/delete', data=VALID_DATA).headers['Location']
    client = sign_in(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    assert client.post('/family/delete', data=VALID_DATA).status_code == 400


def test_attempts_are_rate_limited(app, user):
    client = sign_in(app, user)
    for _ in range(3):
        g.pop('_login_user', None)
        assert client.post('/family/delete', data=dict(VALID_DATA, password='wrong')).status_code == 200
    assert client.post('/family/delete', data=VALID_DATA).status_code == 429


def test_commit_failure_rolls_back_data_membership_sessions_and_audit(app, user, family, graph, monkeypatch):
    client = sign_in(app, user)
    family_id, user_id = family.id, user.id
    monkeypatch.setattr('services.platform.user_session_service.UserSessionService.touch', lambda user: None)
    monkeypatch.setattr(db.session, 'commit', Mock(
        side_effect=OperationalError('commit', {}, Exception('unavailable'))))
    response = client.post('/family/delete', data=VALID_DATA)
    assert b'No deletion was committed' in response.data
    assert db.session.get(Family, family_id) is not None
    assert db.session.get(User, user_id).family_id == family_id
    assert Account.query.filter_by(family_id=family_id).count() == 4
    assert UserSession.query.filter_by(user_id=user_id, revoked_at=None).count() == 1
    assert SecurityEvent.query.filter_by(event_type='household_deleted').count() == 0


def test_foreign_child_link_blocks_deletion_without_mutating_foreign_records(app, user, graph):
    *_, own, private, shared, former, foreign = graph
    # Simulate legacy corrupt data; the ORM write guard would reject this.
    db.session.execute(Transaction.__table__.update().where(
        Transaction.__table__.c.id == foreign['transaction'].id
    ).values(linked_transaction_id=own['transaction'].id))
    db.session.commit()
    db.session.expire(foreign['transaction'])
    response = sign_in(app, user).post('/family/delete', data=VALID_DATA)
    assert b'household data is inconsistent' in response.data
    db.session.refresh(foreign['transaction'])
    assert foreign['transaction'].linked_transaction_id == own['transaction'].id


def test_request_cannot_select_a_different_household(app, user, family, graph):
    _, _, foreign_user, *_ = graph
    foreign_family_id = foreign_user.family_id
    client = sign_in(app, user)
    response = client.post(
        f'/family/delete?family_id={foreign_family_id}', data=dict(VALID_DATA, family_id=foreign_family_id))
    assert b'Your household membership changed' in response.data
    assert db.session.get(Family, foreign_family_id) is not None
    assert db.session.get(User, user.id).family_id == family.id
    response = client.post(f'/family/delete?family_id={foreign_family_id}', data=VALID_DATA)
    assert response.status_code == 302
    assert db.session.get(Family, foreign_family_id) is not None


def test_service_rejects_another_users_identity(app, user, graph):
    _, _, foreign_user, *_ = graph
    client = sign_in(app, user)
    client.get('/account/security')
    with pytest.raises(ValueError, match='own household'):
        HouseholdDeletionService.delete_household(foreign_user, VALID_DATA)


def test_active_other_member_sessions_are_revoked_but_two_factor_and_role_remain(app, user, graph):
    member, *_ = graph
    member.is_active = True
    user.is_site_admin = True
    user.totp_secret = 'JBSWY3DPEHPK3PXP'
    user.totp_enabled_at = _now()
    db.session.commit()
    other_client = sign_in(app, member)
    response = sign_in(app, user).post('/family/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert db.session.get(User, user.id).is_site_admin
    assert db.session.get(User, user.id).two_factor_enabled
    g.pop('_login_user', None)
    assert other_client.get('/account/security').status_code == 302


def test_membership_or_role_change_after_review_requires_a_new_review(app, user, family, monkeypatch):
    client = sign_in(app, user)
    original_preview = HouseholdDeletionService.preview

    def demote_after_preview(user):
        result = original_preview(user)
        user.role = 'member'
        db.session.commit()
        return result

    monkeypatch.setattr(HouseholdDeletionService, 'preview', demote_after_preview)
    response = client.post('/family/delete', data=VALID_DATA)
    assert b'Only an active household owner' in response.data
    assert db.session.get(Family, family.id) is not None


def test_unreviewed_household_table_blocks_deletion(app, user, family, monkeypatch):
    monkeypatch.setattr(
        'services.household.household_deletion_service.HOUSEHOLD_TABLES',
        tuple(name for name in HOUSEHOLD_TABLES if name != 'settings'))
    response = sign_in(app, user).post('/family/delete', data=VALID_DATA)
    assert b'Household data requires a reviewed deletion rule' in response.data
    assert db.session.get(Family, family.id) is not None


def test_unknown_required_dependency_blocks_deletion(app, user, family):
    table = Table('test_household_dependency', db.metadata,
                  Column('id', Integer, primary_key=True),
                  Column('family_ref', Integer, ForeignKey('families.id'), nullable=False))
    table.create(db.engine)
    try:
        db.session.execute(table.insert().values(family_ref=family.id))
        db.session.commit()
        response = sign_in(app, user).post('/family/delete', data=VALID_DATA)
        assert b'Linked records prevent safe' in response.data
        assert db.session.get(Family, family.id) is not None
    finally:
        db.session.rollback()
        table.drop(db.engine)
        db.metadata.remove(table)


def test_missing_reviewed_household_id_does_not_delete(app, user, family):
    data = {key: value for key, value in VALID_DATA.items() if key != 'family_id'}
    response = sign_in(app, user).post('/family/delete', data=data)
    assert b'Reload the household deletion review' in response.data
    assert db.session.get(Family, family.id) is not None


def test_retained_account_can_sign_in_and_join_a_new_household(app, user, graph):
    _, _, foreign_user, *_ = graph
    user_id, password_hash = user.id, user.password_hash
    invite = add(FamilyInvite, family_id=foreign_user.family_id, created_by_id=foreign_user.id,
                 role='member', member_name='New member', allowed_sections='["accounts"]')
    db.session.commit()
    token, new_family_id = invite.token, foreign_user.family_id
    client = sign_in(app, user)
    assert client.post('/family/delete', data=VALID_DATA).status_code == 302
    g.pop('_login_user', None)
    response = client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/account/security')
    g.pop('_login_user', None)
    assert b'Join with my existing account' in client.get(f'/family/join/{token}').data
    another_client = sign_in(app, user)
    g.pop('_login_user', None)
    response = client.post(f'/family/join/{token}')
    assert response.status_code == 302
    assert db.session.get(User, user_id).family_id == new_family_id
    assert db.session.get(User, user_id).password_hash == password_hash
    assert db.session.get(User, user_id).get_allowed_sections() == {'accounts'}
    assert FamilyInvite.query.filter_by(token=token).one().used_by_id == user_id
    g.pop('_login_user', None)
    assert client.get('/account/security').status_code == 200
    g.pop('_login_user', None)
    assert another_client.get('/account/security').status_code == 302
    g.pop('_login_user', None)
    assert client.post(f'/family/join/{token}').status_code == 403


def test_join_existing_requires_recent_auth_and_cannot_move_an_existing_membership(app, user, family):
    foreign_family = add(Family, name='New household')
    invite = add(FamilyInvite, family_id=foreign_family.id, created_by_id=user.id,
                 member_name='New member')
    db.session.commit()
    token = invite.token
    client = sign_in(app, user)
    response = client.post(f'/family/join/{token}')
    assert response.status_code == 302
    assert db.session.get(User, user.id).family_id == family.id
    assert FamilyInvite.query.filter_by(token=token).one().used_at is None
    user.family_id = None
    user.role = 'member'
    UserSession.query.filter_by(user_id=user.id).update({
        'reauthenticated_at': _now() - timedelta(hours=1)})
    db.session.commit()
    g.pop('_login_user', None)
    response = client.get(f'/family/join/{token}')
    assert '/account/confirm' in response.headers['Location']
    assert FamilyInvite.query.filter_by(token=token).one().used_at is None


def test_changed_household_since_get_cannot_delete_the_new_household(app, user, family):
    client = sign_in(app, user)
    assert client.get('/family/delete').status_code == 200
    new_family = add(Family, name='Different household')
    user.family_id = new_family.id
    db.session.commit()
    db.session.expire_all()
    g.pop('_login_user', None)
    response = client.post('/family/delete', data=VALID_DATA)
    assert b'Your household membership changed' in response.data
    assert db.session.get(Family, family.id) is not None
    assert db.session.get(Family, new_family.id) is not None


def test_detached_two_factor_login_still_lands_on_account_security(app, user):
    import pyotp

    user.family_id = None
    user.role = 'member'
    user.totp_secret = 'JBSWY3DPEHPK3PXP'
    user.totp_enabled_at = _now()
    db.session.commit()
    client = app.test_client()
    response = client.post('/login', data={'email': user.email, 'password': 'TestPass1!'})
    assert response.headers['Location'].endswith('/login/two-factor')
    g.pop('_login_user', None)
    response = client.post('/login/two-factor', data={'code': pyotp.TOTP(user.totp_secret).now()})
    assert response.headers['Location'].endswith('/account/security')
