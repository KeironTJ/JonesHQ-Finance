from extensions import db
from models.accounts import Account
from models.family import FamilyInvite
from models.settings import Settings
from models.users import User
from models.vendors import VendorType
from services.finance.vendor_service import DEFAULT_VENDOR_TYPES


def _login(client, user_id):
    from flask import g

    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_household_onboarding_configures_essentials(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/onboarding/', data={
        'payday_day': '25',
        'create_account': '1',
        'account_name': 'Main Current',
        'account_type': 'Current',
        'opening_balance': '125.50',
        'visibility': 'shared',
        'seed_vendor_types': '1',
    })

    assert response.status_code == 302
    assert response.location.endswith('/dashboard')
    db.session.refresh(family)
    db.session.refresh(user)
    account = Account.query.filter_by(family_id=family.id).one()
    assert family.onboarding_version == 1
    assert user.onboarding_version == 1
    assert user.default_account_id == account.id
    assert account.name == 'Main Current'
    assert account.account_type == 'Current'
    assert float(account.balance) == 125.50
    assert Settings.query.filter_by(
        family_id=family.id,
        key='payday_day',
        value='25',
    ).one()
    assert VendorType.query.filter_by(family_id=family.id).count() == len(
        DEFAULT_VENDOR_TYPES
    )


def test_personal_onboarding_only_sets_member_default(app, family, user):
    family.onboarding_version = 1
    shared_account = Account(
        family_id=family.id,
        name='Household Current',
        account_type='Joint',
        is_active=True,
    )
    member = User(
        email='member@example.com',
        name='Member User',
        family_id=family.id,
        role='member',
    )
    member.set_password('TestPass1!')
    db.session.add_all([shared_account, member])
    db.session.commit()

    client = app.test_client()
    _login(client, member.id)
    response = client.post('/onboarding/', data={
        'default_account_id': str(shared_account.id),
    })

    assert response.status_code == 302
    assert response.location.endswith('/dashboard')
    db.session.refresh(member)
    db.session.refresh(family)
    assert member.onboarding_version == 1
    assert member.default_account_id == shared_account.id
    assert family.onboarding_version == 1
    assert Settings.query.filter_by(family_id=family.id).count() == 0
    assert VendorType.query.filter_by(family_id=family.id).count() == 0


def test_household_onboarding_can_be_paused_and_resumed(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/onboarding/skip')

    assert response.status_code == 302
    assert response.location.endswith('/dashboard')
    db.session.refresh(family)
    db.session.refresh(user)
    assert family.onboarding_version == 0
    assert user.onboarding_version == 0
    assert Account.query.filter_by(family_id=family.id).count() == 0

    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert b'Continue setup' in dashboard.data


def test_registration_redirects_new_household_to_onboarding(app):
    from flask import g

    g.pop('_login_user', None)
    client = app.test_client()

    response = client.post('/register', data={
        'household_name': 'New Household',
        'name': 'New Admin',
        'email': 'new-admin@example.com',
        'password': 'StrongPass1!',
        'confirm_password': 'StrongPass1!',
        'submit': 'Create Household',
    })

    assert response.status_code == 302
    assert response.location.endswith('/onboarding/')
    created_user = User.query.filter_by(email='new-admin@example.com').one()
    assert created_user.onboarding_version == 0
    assert created_user.family.onboarding_version == 0


def test_invited_member_redirects_to_personal_onboarding(app, family, user):
    from flask import g

    family.onboarding_version = 1
    invite = FamilyInvite(
        family_id=family.id,
        token='personal-setup-token',
        role='member',
        member_name='Invited Member',
        allowed_sections='["accounts"]',
        created_by_id=user.id,
    )
    db.session.add(invite)
    db.session.commit()
    g.pop('_login_user', None)
    client = app.test_client()

    response = client.post('/family/join/personal-setup-token', data={
        'name': 'Invited Member',
        'email': 'invited@example.com',
        'password': 'TestPass1!',
        'confirm_password': 'TestPass1!',
    })

    assert response.status_code == 302
    assert response.location.endswith('/onboarding/')
    invited_user = User.query.filter_by(email='invited@example.com').one()
    assert invited_user.onboarding_version == 0
    assert invited_user.family_id == family.id