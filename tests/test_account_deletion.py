from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from flask import g
from flask_login.config import COOKIE_NAME
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from models import (
    Account, Balance, Category, CreditCard, CreditCardPromotion, CreditCardTransaction,
    Expense, Family, FamilyInvite, FuelRecord, HouseholdInvite, Income, Loan,
    LoanPayment, LoanTermChange, MonthlyAccountBalance, Pension, PensionSnapshot,
    Plan, PlanItem, RecurringIncome, SecurityEvent, Subscription, Transaction, Trip,
    User, UserRecoveryCode, UserSession, Vehicle,
)
from models.expense_calendar import ExpenseCalendarEntry
from services.platform.account_deletion_service import AccountDeletionService, OWNED_MODELS
from services.platform.user_session_service import _now
from tests.auth_helpers import login_client


TODAY = date(2026, 10, 15)
VALID_DATA = {'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT'}


@pytest.fixture(autouse=True)
def isolate_state(app):
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


def add(model_class, **values):
    row = model_class(**values)
    db.session.add(row)
    db.session.flush()
    return row


@pytest.fixture
def deletion_user(user, family):
    replacement = add(
        User, family_id=family.id, email='replacement@example.com', name='Replacement',
        password_hash=user.password_hash, role='admin')
    db.session.commit()
    return user, replacement


def make_domains(owner, family_id, prefix):
    common = {'family_id': family_id, 'owner_id': owner.id if owner else None}
    account = add(Account, **common, name=prefix, account_type='Current', balance=100)
    card = add(CreditCard, **common, card_name=prefix, annual_apr=0, monthly_apr=0, credit_limit=1000)
    loan = add(Loan, **common, name=prefix, loan_value=100, principal=100, current_balance=100,
               annual_apr=0, monthly_apr=0, monthly_payment=10, start_date=TODAY, term_months=10)
    pension = add(Pension, **common, provider=prefix, current_value=100)
    vehicle = add(Vehicle, **common, make=prefix, model='Car', registration=prefix)
    plan = add(Plan, **common, title=prefix)
    income = add(Income, **common, pay_date=TODAY, gross_annual_income=12000,
                 gross_monthly_income=1000, take_home=900)
    recurring = add(RecurringIncome, **common, start_date=TODAY, pay_day=15,
                    gross_annual_income=12000, tax_code='1257L')
    expense = add(Expense, **common, date=TODAY, description=prefix,
                  expense_type='Hotel', cost=10, total_cost=10)
    category = add(Category, family_id=family_id, name='General', category_type='expense')
    transaction = add(Transaction, family_id=family_id, account_id=account.id,
                      category_id=category.id, amount=-10, transaction_date=TODAY, description=prefix)
    cc_transaction = add(CreditCardTransaction, family_id=family_id, credit_card_id=card.id,
                         date=TODAY, amount=-10, transaction_type='Purchase')
    fuel = add(FuelRecord, family_id=family_id, vehicle_id=vehicle.id, date=TODAY,
               mileage=100, cost=10, gallons=2)
    for model, values in (
        (Balance, dict(account_id=account.id, balance=100, balance_date=TODAY)),
        (MonthlyAccountBalance, dict(account_id=account.id, year_month='2026-10')),
        (CreditCardPromotion, dict(credit_card_id=card.id, promotion_type='purchase',
                                  apr_rate=0, start_date=TODAY, end_date=TODAY)),
        (LoanPayment, dict(loan_id=loan.id, date=TODAY, period=1, opening_balance=100,
                          payment_amount=10, amount_paid_off=10, closing_balance=90)),
        (LoanTermChange, dict(loan_id=loan.id, effective_date=TODAY)),
        (PensionSnapshot, dict(pension_id=pension.id, review_date=TODAY, value=100)),
        (Trip, dict(vehicle_id=vehicle.id, date=TODAY, total_miles=10, fuel_log_entry_id=fuel.id)),
        (PlanItem, dict(plan_id=plan.id, title=prefix, transaction_id=transaction.id)),
        (ExpenseCalendarEntry, dict(expense_id=expense.id, date=TODAY, description=prefix)),
        (Subscription, dict(account_id=account.id, name=prefix, amount=-10, start_date=TODAY)),
    ):
        add(model, family_id=family_id, **values)
    return dict(account=account, card=card, loan=loan, pension=pension, vehicle=vehicle, plan=plan,
                income=income, recurring=recurring, expense=expense, transaction=transaction,
                cc_transaction=cc_transaction, category=category)


@pytest.fixture
def graph(deletion_user, family):
    user, replacement = deletion_user
    other_family = add(Family, name='Foreign family')
    foreign_user = add(User, email='foreign@example.com', name='Foreign', family_id=other_family.id,
                       password_hash=user.password_hash)
    own = make_domains(user, family.id, 'Own')
    shared = make_domains(None, family.id, 'Shared')
    private = make_domains(replacement, family.id, 'Other private')
    foreign = make_domains(foreign_user, other_family.id, 'Foreign')
    own['income'].transaction_id = shared['transaction'].id
    own['expense'].bank_transaction_id = shared['transaction'].id
    own['cc_transaction'].bank_transaction_id = shared['transaction'].id
    shared['transaction'].loan_id = own['loan'].id
    shared['transaction'].credit_card_id = own['card'].id
    shared['transaction'].linked_transaction_id = own['transaction'].id
    own['transaction'].linked_transaction_id = shared['transaction'].id
    shared['cc_transaction'].linked_cc_transaction_id = own['cc_transaction'].id
    shared['income'].recurring_income_id = own['recurring'].id
    shared['expense'].income_id = own['income'].id
    replacement.default_account_id = own['account'].id
    add(FamilyInvite, family_id=family.id, member_name='Unused', created_by_id=user.id)
    add(FamilyInvite, family_id=family.id, member_name='Kept', created_by_id=replacement.id, used_by_id=user.id)
    add(HouseholdInvite, token_hash='a' * 64, created_by_id=user.id, expires_at=_now() + timedelta(days=1))
    add(UserRecoveryCode, user_id=user.id, code_hash='b' * 64)
    add(SecurityEvent, user_id=user.id, family_id=family.id, event_type='login_success')
    db.session.commit()
    return own, shared, private, foreign


def sign_in(app, user, remember=False):
    client = app.test_client()
    login_client(client, user.id, remember=remember)
    return client


def row_exists(model, row_id):
    return db.session.execute(select(model.id).where(model.id == row_id)).first() is not None


def test_deletion_removes_private_domains_but_preserves_shared_and_other_households(app, deletion_user, graph):
    user, replacement = deletion_user
    own, shared, private, foreign = graph
    user_id = user.id
    client = sign_in(app, user)
    other_client = sign_in(app, user)
    response = client.post('/account/security/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    assert not row_exists(User, user_id)
    for model in OWNED_MODELS:
        assert db.session.execute(select(model.id).where(model.owner_id == user_id)).first() is None
    for key, model in (
        ('account', Account), ('card', CreditCard), ('loan', Loan), ('pension', Pension),
        ('vehicle', Vehicle), ('plan', Plan), ('income', Income), ('recurring', RecurringIncome),
        ('expense', Expense), ('transaction', Transaction), ('cc_transaction', CreditCardTransaction),
    ):
        assert not row_exists(model, own[key].id)
        for retained in (shared, private, foreign):
            assert row_exists(model, retained[key].id)
    for model in (
        Balance, MonthlyAccountBalance, CreditCardPromotion, LoanPayment, LoanTermChange,
        PensionSnapshot, Trip, FuelRecord, PlanItem, ExpenseCalendarEntry, Subscription,
    ):
        assert db.session.execute(select(db.func.count()).select_from(model)).scalar() == 3
    db.session.expire_all()
    kept = db.session.get(Transaction, shared['transaction'].id)
    assert kept.amount == -10
    assert kept.loan_id is None
    assert kept.credit_card_id is None
    assert kept.linked_transaction_id is None
    assert db.session.get(Account, shared['account'].id).balance == 100
    assert db.session.get(User, replacement.id).default_account_id is None
    assert db.session.get(CreditCardTransaction, shared['cc_transaction'].id).linked_cc_transaction_id is None
    assert db.session.get(Income, shared['income'].id).recurring_income_id is None
    assert db.session.get(Expense, shared['expense'].id).income_id is None
    assert FamilyInvite.query.count() == 1
    assert FamilyInvite.query.one().used_by_id is None
    assert HouseholdInvite.query.one().created_by_id is None
    assert HouseholdInvite.query.one().revoked_at is not None
    assert SecurityEvent.query.filter_by(user_id=user_id).count() == 0
    assert SecurityEvent.query.filter_by(event_type='login_success').one().user_id is None
    assert UserRecoveryCode.query.filter_by(user_id=user_id).count() == 0
    assert UserSession.query.filter_by(user_id=user_id).count() == 0
    assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []
    g.pop('_login_user', None)
    assert other_client.get('/account/security').status_code == 302


def test_preview_is_read_only_and_lists_all_owned_domains(app, deletion_user, graph):
    user, _ = deletion_user
    own, *_ = graph
    client = sign_in(app, user)
    response = client.get('/account/security/delete')
    assert response.status_code == 200
    assert b'DELETE MY ACCOUNT' in response.data
    assert b'Shared financial records remain' in response.data
    assert row_exists(User, user.id)
    assert row_exists(Account, own['account'].id)
    with app.test_request_context('/'):
        from flask_login import login_user
        login_user(user)
        counts = AccountDeletionService.preview(user)
        assert counts['accounts'] == counts['plans'] == counts['transactions'] == 1


@pytest.mark.parametrize('data,message', [
    ({'password': 'WrongPassword1!', 'confirmation': 'DELETE MY ACCOUNT'}, b'password was not correct'),
    ({'password': 'TestPass1!', 'confirmation': 'delete my account'}, b'Type DELETE MY ACCOUNT exactly'),
    ({'password': '', 'confirmation': 'DELETE MY ACCOUNT'}, b'This field is required'),
])
def test_invalid_confirmation_does_not_delete(app, deletion_user, data, message):
    user, _ = deletion_user
    response = sign_in(app, user).post('/account/security/delete', data=data)
    assert response.status_code == 200
    assert message in response.data
    assert row_exists(User, user.id)


def test_last_admin_cannot_delete_until_another_active_admin_exists(app, user, family):
    client = sign_in(app, user)
    for role, active in (('member', True), ('admin', False)):
        add(User, email=f'ineligible-{role}@example.com', name='Not eligible',
                          family_id=family.id, password_hash=user.password_hash, role=role, is_active=active)
    db.session.commit()
    response = client.post('/account/security/delete', data=VALID_DATA)
    assert b'Appoint another active household owner' in response.data
    assert row_exists(User, user.id)


def test_site_admin_must_revoke_role_first(app, deletion_user):
    user, _ = deletion_user
    user.is_site_admin = True
    user.totp_secret = 'JBSWY3DPEHPK3PXP'
    user.totp_enabled_at = _now()
    db.session.commit()
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert b'Revoke your site-admin role' in response.data
    assert row_exists(User, user.id)


def test_removed_member_can_delete_owned_records_in_former_household(app, deletion_user, graph):
    user, _ = deletion_user
    user.family_id = None
    user.role = 'member'
    db.session.commit()
    user_id = user.id
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert not row_exists(User, user_id)
    assert Account.query.filter_by(name='Own').count() == 0
    assert Account.query.filter_by(name='Shared').count() == 1


def test_deletion_failure_rolls_back_everything(app, deletion_user, graph, monkeypatch):
    user, _ = deletion_user
    client = sign_in(app, user)
    monkeypatch.setattr(db.session, 'commit', Mock(
        side_effect=OperationalError('commit', {}, Exception('unavailable'))))
    # Avoid the separate request-session touch commit so failure occurs at the deletion boundary.
    monkeypatch.setattr('services.platform.user_session_service.UserSessionService.touch', lambda user: None)
    response = client.post('/account/security/delete', data=VALID_DATA)
    assert response.status_code == 200
    assert b'No deletion was committed' in response.data
    assert row_exists(User, user.id)
    assert Account.query.filter_by(name='Own').count() == 1
    assert HouseholdInvite.query.one().revoked_at is None


def test_cross_household_corrupt_child_blocks_deletion(app, deletion_user, graph):
    user, _ = deletion_user
    own, _, _, foreign = graph
    # Simulate legacy corrupt data; the ORM write guard would reject this.
    db.session.execute(Balance.__table__.insert().values(
        family_id=foreign['account'].family_id, account_id=own['account'].id,
        balance=5, balance_date=TODAY))
    db.session.commit()
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert b'household data is inconsistent' in response.data
    assert row_exists(User, user.id)


def test_requires_login_recent_password_and_csrf(app, deletion_user, monkeypatch):
    user, _ = deletion_user
    assert app.test_client().post('/account/security/delete', data=VALID_DATA).status_code == 302
    client = sign_in(app, user)
    UserSession.query.filter_by(user_id=user.id).update({
        'reauthenticated_at': _now() - timedelta(hours=1)})
    db.session.commit()
    g.pop('_login_user', None)
    response = client.post('/account/security/delete', data=VALID_DATA)
    assert '/account/confirm' in response.headers['Location']
    sign_in_client = sign_in(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    assert sign_in_client.post('/account/security/delete', data=VALID_DATA).status_code == 400
    assert row_exists(User, user.id)


def test_wrong_password_attempts_are_rate_limited(app, deletion_user):
    user, _ = deletion_user
    client = sign_in(app, user)
    bad = dict(VALID_DATA, password='wrong')
    for _ in range(3):
        g.pop('_login_user', None)
        assert client.post('/account/security/delete', data=bad).status_code == 200
    assert client.post('/account/security/delete', data=bad).status_code == 429
    assert row_exists(User, user.id)


def test_service_rejects_attempt_to_delete_someone_else(app, deletion_user):
    user, replacement = deletion_user
    client = sign_in(app, user)
    client.get('/account/security')
    with pytest.raises(ValueError, match='your own account'):
        AccountDeletionService.delete_account(replacement, VALID_DATA)
    assert row_exists(User, replacement.id)


def test_private_transaction_cycles_and_sources_delete_without_fk_violations(app, deletion_user, graph):
    user, _ = deletion_user
    own, *_ = graph
    own['income'].transaction_id = own['transaction'].id
    own['expense'].income_id = own['income'].id
    own['expense'].bank_transaction_id = own['transaction'].id
    own['expense'].credit_card_transaction_id = own['cc_transaction'].id
    own['cc_transaction'].bank_transaction_id = own['transaction'].id
    own['cc_transaction'].linked_cc_transaction_id = own['cc_transaction'].id
    own['cc_transaction'].statement_id = own['cc_transaction'].id
    own['transaction'].linked_transaction_id = own['transaction'].id
    user.default_account_id = own['account'].id
    subscription = Subscription.query.filter_by(account_id=own['account'].id).one()
    subscription.account_id = None
    subscription.credit_card_id = own['card'].id
    db.session.commit()
    user_id = user.id
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert not row_exists(User, user_id)
    assert db.session.execute(text('PRAGMA foreign_key_check')).all() == []


def test_deletion_clears_remember_cookie(app, deletion_user):
    user, _ = deletion_user
    client = sign_in(app, user, remember=True)
    cookie_name = app.config.get('REMEMBER_COOKIE_NAME', COOKIE_NAME)
    client.set_cookie(cookie_name, 'previous-remember-token')
    response = client.post('/account/security/delete', data=VALID_DATA)
    assert response.status_code == 302
    assert client.get_cookie(cookie_name) is None
    with client.session_transaction() as session:
        assert '_user_id' not in session


def test_replacement_admin_deactivated_after_preview_blocks_deletion(app, deletion_user, monkeypatch):
    user, replacement = deletion_user
    original_preview = AccountDeletionService.preview

    def deactivate_after_preview(user):
        counts = original_preview(user)
        replacement.is_active = False
        db.session.commit()
        return counts

    monkeypatch.setattr(AccountDeletionService, 'preview', deactivate_after_preview)
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert b'Appoint another active household owner' in response.data
    assert row_exists(User, user.id)


@pytest.mark.parametrize('unhandled,message', [
    (Plan, b'Private records require a reviewed deletion rule'),
    (LoanPayment, b'Linked records prevent safe account deletion'),
])
def test_unhandled_dependencies_block_deletion(app, deletion_user, graph, monkeypatch, unhandled, message):
    user, _ = deletion_user
    original_plan = AccountDeletionService._plan

    def incomplete_plan(user):
        plan = original_plan(user)
        plan[unhandled.__table__] = {}
        return plan

    monkeypatch.setattr(AccountDeletionService, '_plan', incomplete_plan)
    response = sign_in(app, user).post('/account/security/delete', data=VALID_DATA)
    assert message in response.data
    assert row_exists(User, user.id)
    assert Account.query.filter_by(name='Own').count() == 1
