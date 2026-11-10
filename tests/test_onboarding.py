from tests.auth_helpers import login_client
from extensions import db
from models.accounts import Account
from models.family import FamilyInvite, HouseholdMembership
from models.settings import Settings
from models.site_settings import SiteSettings
from models.users import User
from models.vendors import VendorType
from services.finance.vendor_service import DEFAULT_VENDOR_TYPES


def _login(client, user_id):
    from flask import g

    g.pop('_login_user', None)
    login_client(client, user_id)


def test_household_onboarding_configures_essentials(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/finance/onboarding/', data={
        'payday_day': '25',
        'create_account': '1',
        'account_name': 'Main Current',
        'account_type': 'Current',
        'opening_balance': '125.50',
        'visibility': 'shared',
        'seed_vendor_types': '1',
    })

    assert response.status_code == 302
    assert response.location.endswith('/finance/dashboard')
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
    response = client.post('/finance/onboarding/', data={
        'default_account_id': str(shared_account.id),
    })

    assert response.status_code == 302
    assert response.location.endswith('/finance/dashboard')
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

    response = client.post('/finance/onboarding/skip')

    assert response.status_code == 302
    assert response.location.endswith('/finance/dashboard')
    db.session.refresh(family)
    db.session.refresh(user)
    assert family.onboarding_version == 0
    assert user.onboarding_version == 0
    assert Account.query.filter_by(family_id=family.id).count() == 0

    dashboard = client.get('/finance/dashboard')
    assert dashboard.status_code == 200
    assert b'Continue setup' in dashboard.data


def test_registration_opens_hub_before_optional_finance_setup(app):
    from flask import g
    from services.platform.household_invite_service import HouseholdInviteService

    g.pop('_login_user', None)
    client = app.test_client()
    _, token = HouseholdInviteService.create_invite({})

    response = client.post('/register', data={
        'invite_token': token,
        'household_name': 'New Household',
        'name': 'New Admin',
        'email': 'new-admin@example.com',
        'password': 'StrongPass1!',
        'confirm_password': 'StrongPass1!',
        'submit': 'Create Household',
    })

    assert response.status_code == 302
    assert response.location.endswith('/central/')
    created_user = User.query.filter_by(email='new-admin@example.com').one()
    assert created_user.onboarding_version == 0
    assert created_user.family.onboarding_version == 0


def test_public_intro_links_to_household_creation_when_registration_is_open(app):
    from flask import g

    g.pop('_login_user', None)
    app.config['ALLOW_OPEN_REGISTRATION'] = True

    client = app.test_client()
    for path in ('/intro', '/login'):
        response = client.get(path)
        assert response.status_code == 200
        assert b'href="/register"' in response.data
        assert b'Create your household' in response.data
    assert b'New households can sign up' in client.get('/intro').data


def test_public_intro_hides_household_creation_when_signups_are_paused(app):
    from flask import g

    g.pop('_login_user', None)
    app.config['ALLOW_OPEN_REGISTRATION'] = True
    db.session.add(SiteSettings(id=1, household_signups_paused=True))
    db.session.commit()

    client = app.test_client()
    for path in ('/intro', '/login'):
        response = client.get(path)
        assert response.status_code == 200
        assert b'href="/register"' not in response.data
        assert b'Create your household' not in response.data


def test_authenticated_intro_links_to_central_hub(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/intro')

    assert response.status_code == 200
    assert b'href="/central/"' in response.data
    assert b'Go to Central Hub' in response.data


def test_invited_member_opens_hub_before_optional_finance_setup(app, family, user):
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

    response = client.post('/central/family/join/personal-setup-token', data={
        'name': 'Invited Member',
        'email': 'invited@example.com',
        'password': 'TestPass1!',
        'confirm_password': 'TestPass1!',
    })

    assert response.status_code == 302
    assert response.location.endswith('/central/')
    invited_user = User.query.filter_by(email='invited@example.com').one()
    assert invited_user.onboarding_version == 0
    assert invited_user.family_id == family.id
    membership = HouseholdMembership.query.filter_by(
        user_id=invited_user.id, family_id=family.id,
    ).one()
    assert membership.role == 'member'
    assert membership.allowed_modules == ['finance', 'household']
    assert invited_user.get_allowed_sections() == {'accounts'}