import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g, url_for
from flask_login import login_user
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family, HouseholdMembership
from models.users import SecurityEvent, User
from services.household.household_access_service import HouseholdAccessService
from services.platform.account_deletion_service import AccountDeletionService
from services.platform.data_export_service import DataExportService
from services.platform.module_access_service import ModuleAccessService
from services.platform.module_registry import ModuleRegistry
from tests.auth_helpers import login_client
from tests.test_account_security import make_stale


def adult(family, email='adult@example.com', role='member'):
    member = User(
        family_id=family.id, email=email, name='Adult member',
        role=role, allowed_sections='["accounts", "transactions"]',
    )
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()
    return member


def child(family, guardian):
    member = adult(family, 'child@example.com')
    member.account_type = 'child'
    member.guardian_id = guardian.id
    member.get_active_household_membership().allowed_modules = ['household']
    db.session.commit()
    return member


@pytest.mark.parametrize('kind', ['child', 'member', 'owner'])
def test_every_finance_route_and_method_denied_without_module_access(app, family, user, kind):
    member = child(family, user) if kind == 'child' else adult(
        family, role='admin' if kind == 'owner' else 'member',
    )
    membership = member.get_active_household_membership()
    membership.allowed_modules = ['household']
    # Even corrupt owner/Finance-section choices cannot bypass the child baseline.
    if kind == 'child':
        membership.role = 'admin'
        membership.allowed_sections = None
        membership.allowed_modules = ['finance', 'household']
    db.session.commit()
    client = app.test_client()
    login_client(client, member.id)
    routes = []
    with app.test_request_context():
        for rule in app.url_map.iter_rules():
            if ModuleRegistry.module_for_blueprint(rule.endpoint.rsplit('.', 1)[0]) is None:
                continue
            values = {
                name: (1 if converter.__class__.__name__ == 'IntegerConverter' else 'household')
                for name, converter in rule._converters.items()
            }
            routes.append((rule, url_for(rule.endpoint, **values)))
    assert len(routes) > 100
    for rule, path in routes:
        for method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
            if method in rule.methods:
                response = client.open(path, method=method)
                assert response.status_code == 403, (method, path, response.status_code)
    for path in ('/account/security/export', '/family/assignment-labels'):
        assert client.post(path).status_code == 403


def test_revocation_is_immediate_and_does_not_change_section_choices(app, family, user):
    member = adult(family)
    owner_client = app.test_client()
    member_client = app.test_client()
    login_client(owner_client, user.id)
    login_client(member_client, member.id)
    g.pop('_login_user', None)
    assert member_client.get('/accounts').status_code == 200
    g.pop('_login_user', None)
    response = owner_client.post(f'/hub/settings/access/members/{member.id}', data={'modules': ['household']})
    assert response.status_code == 302
    assert member.get_active_household_membership().allowed_sections == '["accounts", "transactions"]'
    g.pop('_login_user', None)
    assert member_client.get('/accounts').status_code == 403
    assert member_client.get('/dashboard').status_code == 403
    assert SecurityEvent.query.filter_by(event_type='module_access_updated').count() == 1
    g.pop('_login_user', None)
    owner_client.post(f'/hub/settings/access/members/{member.id}', data={'modules': ['finance', 'household']})
    g.pop('_login_user', None)
    assert member_client.get('/accounts').status_code == 200
    assert member_client.get('/income').status_code == 403


def test_module_grants_are_household_scoped(app, family, user):
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id, family_id=other_family.id, role='admin', allowed_modules=['household'],
    ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    assert client.get('/dashboard').status_code == 200
    client.post('/family/select', data={'family_id': other_family.id})
    assert client.get('/dashboard').status_code == 403
    assert client.get('/hub/settings/access').status_code == 200
    client.post('/family/select', data={'family_id': family.id})
    assert client.get('/dashboard').status_code == 200


def test_child_navigation_search_preferences_and_exports_do_not_offer_finance(app, family, user):
    member = child(family, user)
    member.preferences = {'default_workspace': 'finance'}
    db.session.commit()
    client = app.test_client()
    login_client(client, member.id)
    assert client.get('/').location.endswith('/hub')
    for path in ('/hub', '/preferences', '/hub/settings', '/account/security'):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        for target in ('/dashboard', '/accounts', '/preferences/finance', '/account/security/export', '/family/'):
            assert f'href="{target}"' not in html
            assert f'action="{target}"' not in html
        assert 'value="finance"' not in html
    response = client.post('/preferences/workspace', data={'default_workspace': 'finance'})
    assert response.status_code == 302
    assert b'This workspace is not enabled' in client.get(response.location).data
    assert client.post('/preferences/appearance', json={'mode': 'dark', 'palette': 'green'}).status_code == 200
    with app.test_request_context():
        login_user(member)
        with pytest.raises(ValueError, match='Finance access'):
            DataExportService.create(member)


def test_managed_child_creation_uses_owner_as_guardian_and_ignores_extra_fields(app, family, user):
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/hub/settings/children/create', data={
        'name': 'Managed member', 'email': 'new-child@example.com',
        'password': 'TestPass1!', 'confirm_password': 'TestPass1!',
        'role': 'admin', 'account_type': 'adult', 'guardian_id': 999,
        'modules': ['finance'], 'family_id': 999, 'sections': ['income'],
    })
    assert response.status_code == 302
    member = User.query.filter_by(email='new-child@example.com').one()
    assert member.is_managed_child
    assert member.guardian_id == user.id
    assert member.check_password('TestPass1!')
    membership = member.get_active_household_membership()
    assert membership.family_id == family.id
    assert membership.role == 'member'
    assert membership.allowed_sections == '[]'
    assert membership.allowed_modules == ['household']
    assert SecurityEvent.query.filter_by(event_type='managed_child_created').count() == 1
    login_client(client, member.id)
    assert client.post('/login', data={'email': member.email, 'password': 'TestPass1!'}).status_code == 302
    assert client.get('/hub').status_code == 200
    assert client.get('/dashboard').status_code == 403


@pytest.mark.parametrize('payload', [
    {'name': '', 'email': 'valid@example.com'},
    {'name': 'Child', 'email': 'invalid'},
    {'name': 'Child', 'email': 'admin@example.com'},
    {'name': 'Child', 'email': 'new@example.com', 'password': 'weak'},
    {'name': 'Child', 'email': 'new@example.com', 'confirm_password': 'Different1!'},
])
def test_invalid_child_creation_reports_error_without_partial_account(app, user, payload):
    client = app.test_client()
    login_client(client, user.id)
    values = {'password': 'TestPass1!', 'confirm_password': 'TestPass1!', **payload}
    response = client.post('/hub/settings/children/create', data=values)
    assert response.status_code == 302
    assert User.query.count() == 1
    assert SecurityEvent.query.filter_by(event_type='managed_child_created').count() == 0


def test_owner_cannot_grant_child_finance_or_promote_through_legacy_routes(app, family, user):
    member = child(family, user)
    client = app.test_client()
    login_client(client, user.id)
    for path, data in (
        (f'/hub/settings/access/members/{member.id}', {'modules': ['finance']}),
        (f'/family/members/{member.id}/role', {'role': 'admin'}),
        (f'/family/members/{member.id}/update', {'role': 'admin', 'sections': ['accounts']}),
        (f'/settings/access/members/{member.id}', {'sections': ['accounts']}),
    ):
        response = client.post(path, data=data)
        assert response.status_code == 302
        assert b'alert-danger' in client.get(response.location).data
    assert member.is_managed_child
    assert member.get_active_household_membership().role == 'member'
    assert member.get_active_household_membership().allowed_modules == ['household']


def test_only_designated_guardian_can_transfer_or_release_child(app, family, user):
    member = child(family, user)
    other_owner = adult(family, role='admin')
    client = app.test_client()
    login_client(client, other_owner.id)
    assert client.post(f'/account/children/{member.id}', data={'action': 'release'}).status_code == 404
    assert member.is_managed_child
    login_client(client, user.id)
    client.post(f'/account/children/{member.id}', data={
        'action': 'transfer', 'guardian_id': other_owner.id,
    })
    assert member.guardian_id == other_owner.id
    assert client.post(f'/account/children/{member.id}', data={'action': 'release'}).status_code == 404
    login_client(client, other_owner.id)
    client.post(f'/account/children/{member.id}', data={'action': 'release'})
    assert not member.is_managed_child
    assert member.guardian_id is None
    assert member.get_active_household_membership().allowed_modules == ['household']
    login_client(client, member.id)
    assert client.get('/dashboard').status_code == 403


def test_guardian_cannot_transfer_to_child_or_unrelated_adult(app, family, user):
    member = child(family, user)
    other_family = Family(name='Other')
    db.session.add(other_family)
    db.session.commit()
    outsider = adult(other_family)
    client = app.test_client()
    login_client(client, user.id)
    for guardian_id in (member.id, outsider.id, 99999):
        response = client.post(f'/account/children/{member.id}', data={
            'action': 'transfer', 'guardian_id': guardian_id,
        })
        assert response.status_code == 302
        assert member.guardian_id == user.id


def test_child_cannot_manage_permissions_join_or_reach_operator_pages(app, family, user):
    member = child(family, user)
    member.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    login_client(client, member.id)
    for path in (
        '/hub/settings/access', '/account/children', '/family/', '/family/join/invalid',
        '/site-admin/', '/site-admin/console/', '/account/security/delete', '/register',
    ):
        assert client.get(path).status_code == 403, path
    for path in (
        '/hub/settings/children/create', f'/account/children/{member.id}',
        f'/hub/settings/access/members/{member.id}',
    ):
        assert client.post(path).status_code == 403, path


def test_module_changes_require_owner_recent_auth_and_scoped_member(app, family, user):
    member = adult(family)
    other_family = Family(name='Other')
    db.session.add(other_family)
    db.session.commit()
    outsider = adult(other_family, 'outsider@example.com')
    client = app.test_client()
    login_client(client, user.id)
    assert client.post(f'/hub/settings/access/members/{outsider.id}', data={'modules': []}).status_code == 404
    response = client.post(f'/hub/settings/access/members/{member.id}', data={'modules': ['unknown']})
    assert response.status_code == 302
    assert member.get_active_household_membership().allowed_modules == ['finance', 'household']
    make_stale(user)
    g.pop('_login_user', None)
    assert client.post(
        f'/hub/settings/access/members/{member.id}', data={'modules': []},
    ).location.startswith('/account/confirm')
    login_client(client, member.id)
    assert client.get('/hub/settings/access').status_code == 403
    assert client.post(f'/hub/settings/access/members/{user.id}').status_code == 403


def test_guardian_cannot_delete_account_until_child_management_resolved(app, family, user):
    child(family, user)
    with app.test_request_context():
        login_user(user)
        with pytest.raises(ValueError, match='Transfer guardianship'):
            AccountDeletionService.preview(user)


@pytest.mark.parametrize('action', ['modules', 'create', 'guardian'])
def test_access_writes_require_recent_auth_and_csrf(app, family, user, monkeypatch, action):
    member = child(family, user)
    paths = {
        'modules': f'/hub/settings/access/members/{member.id}',
        'create': '/hub/settings/children/create',
        'guardian': f'/account/children/{member.id}',
    }
    client = app.test_client()
    login_client(client, user.id)
    make_stale(user)
    g.pop('_login_user', None)
    assert client.post(paths[action]).location.startswith('/account/confirm')
    login_client(client, user.id)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    assert client.post(paths[action]).status_code == 400
    assert member.is_managed_child
    assert member.get_active_household_membership().allowed_modules == ['household']


def test_owner_can_restore_own_module_access_without_finance(app, user):
    client = app.test_client()
    login_client(client, user.id)
    path = f'/hub/settings/access/members/{user.id}'
    assert client.post(path, data={'modules': []}).status_code == 302
    assert client.get('/dashboard').status_code == 403
    assert client.get('/hub/settings/access').status_code == 200
    assert client.post(path, data={'modules': ['finance', 'household']}).status_code == 302
    assert client.get('/dashboard').status_code == 200


@pytest.mark.parametrize('kind', ['modules', 'create', 'guardian'])
def test_access_write_failures_rollback_data_and_audit(app, family, user, monkeypatch, kind):
    member = child(family, user)
    client = app.test_client()
    login_client(client, user.id)

    def fail():
        raise SQLAlchemyError('Simulated failure')

    monkeypatch.setattr(db.session, 'commit', fail)
    path, data = {
        'modules': (f'/hub/settings/access/members/{member.id}', {'modules': []}),
        'create': ('/hub/settings/children/create', {
            'name': 'New child', 'email': 'new@example.com',
            'password': 'TestPass1!', 'confirm_password': 'TestPass1!',
        }),
        'guardian': (f'/account/children/{member.id}', {'action': 'release'}),
    }[kind]
    response = client.post(path, data=data)
    assert response.status_code == 302
    assert member.is_managed_child
    assert member.get_active_household_membership().allowed_modules == ['household']
    assert User.query.filter_by(email='new@example.com').first() is None
    assert SecurityEvent.query.filter(SecurityEvent.event_type.in_([
        'module_access_updated', 'managed_child_released', 'managed_child_created',
    ])).count() == 0
    assert b'No changes were saved.' in client.get(response.location).data


def test_module_access_migration_preserves_existing_adults_and_grants(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'c81d4e6f9a20_add_module_access_and_managed_children.py'
    spec = importlib.util.spec_from_file_location('module_access_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    metadata = sa.MetaData()
    sa.Table('users', metadata, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('household_memberships', metadata, sa.Column('id', sa.Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text('INSERT INTO users (id) VALUES (1)'))
        connection.execute(sa.text('INSERT INTO household_memberships (id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text('SELECT account_type, guardian_id FROM users')).one() == ('adult', None)
            grants = connection.execute(sa.text('SELECT allowed_modules FROM household_memberships')).scalar_one()
            assert '"finance"' in grants and '"household"' in grants
            assert sa.inspect(connection).get_foreign_keys('users')[0]['name'] == 'fk_users_guardian_id_users'
            migration.downgrade()
            assert {col['name'] for col in sa.inspect(connection).get_columns('users')} == {'id'}
            migration.upgrade()
    engine.dispose()
