import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.family import Family
from models.settings import Settings
from models.users import User
from models.vendors import Vendor
from services.platform.preference_service import PreferenceService
from services.platform.settings_service import SettingsService
from tests.auth_helpers import login_client


def _client(app, user):
    client = app.test_client()
    login_client(client, user.id)
    return client


def _member(family):
    member = User(
        email='member@example.com', name='Member', family_id=family.id,
        role='member', allowed_sections='["categories", "vendors"]',
    )
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()
    return member


@pytest.mark.parametrize('section', SettingsService.SECTIONS)
def test_owner_settings_pages_have_independent_forms(app, user, section):
    response = _client(app, user).get(f'/settings/modules/{section}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'action="/settings/modules/{section}"' in html
    assert 'Applies to this household' in html
    assert 'name="dashboard.networth_expanded"' not in html
    assert 'name="default_account_id"' not in html


def test_settings_hub_links_to_all_independent_editors(app, user):
    html = _client(app, user).get('/settings').get_data(as_text=True)
    for section in SettingsService.SECTIONS:
        assert f'href="/settings/modules/{section}"' in html
    for path in ('/preferences', '/settings/tax', '/vendors/types', '/family/'):
        assert f'href="{path}"' in html
    assert 'action="/settings/update"' not in html


@pytest.mark.parametrize('path', [
    '/settings', '/settings/modules/household', '/settings/modules/expenses',
    '/settings/modules/credit-cards', '/settings/modules/networth', '/settings/tax',
])
def test_members_cannot_read_or_write_household_settings(app, family, path):
    client = _client(app, _member(family))
    assert client.get(path).status_code == 403
    assert client.post(path, data={'payday_day': '23'}).status_code == 403
    assert Settings.query.count() == 0


@pytest.mark.parametrize('key, path', [
    ('categories.collapse_all_default', '/categories/'),
    ('vendors.collapse_all_default', '/vendors/'),
])
def test_member_preferences_are_personal_and_work_on_module_pages(app, family, user, key, path):
    member = _member(family)
    client = _client(app, member)
    response = client.post('/preferences/save', json={
        'key': key, 'value': True,
        'user_id': user.id, 'family_id': family.id,
    })
    assert response.status_code == 200
    assert member.preferences == {key: True}
    assert not user.preferences
    assert Settings.query.count() == 0
    html = client.get('/preferences').get_data(as_text=True)
    assert 'Personal preferences' in html
    assert 'href="/settings"' not in html
    module_html = client.get(path).get_data(as_text=True)
    assert 'id="collapseAllDefault" checked' in module_html
    assert 'fetch(\'/settings/save_preference\'' not in module_html
    owner_html = _client(app, user).get(path).get_data(as_text=True)
    assert 'id="collapseAllDefault" checked' not in owner_html


@pytest.mark.parametrize('payload', [
    {'key': 'expenses.auto_sync', 'value': True},
    {'key': 'categories.collapse_all_default', 'value': 'true'},
    {'key': ['categories.collapse_all_default'], 'value': True},
    ['categories.collapse_all_default', True],
    {},
])
def test_invalid_personal_preferences_return_explicit_errors(app, user, payload):
    response = _client(app, user).post('/preferences/save', json=payload)
    assert response.status_code == 400
    assert response.get_json()['success'] is False
    assert response.get_json()['error']
    assert not user.preferences


def test_preferences_require_login(app):
    g.pop('_login_user', None)
    client = app.test_client()
    assert client.get('/preferences').status_code == 302
    assert client.post('/preferences/save', json={}).status_code == 302


def test_preference_database_failure_returns_error_and_rolls_back(app, user, monkeypatch):
    client = _client(app, user)

    def fail_commit():
        raise sa.exc.SQLAlchemyError('Test write failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)
    response = client.post('/preferences/save', json={
        'key': 'vendors.collapse_all_default', 'value': True,
    })
    assert response.status_code == 500
    assert response.get_json()['success'] is False
    assert 'Unable to save' in response.get_json()['error']
    assert not user.preferences


def test_personal_default_account_can_be_selected_and_reset(app, family, user):
    account = Account(family_id=family.id, name='Current', account_type='Current', is_active=True)
    db.session.add(account)
    db.session.commit()
    client = _client(app, user)
    assert client.post('/preferences', data={'default_account_id': str(account.id)}).status_code == 302
    assert user.default_account_id == account.id
    assert client.post('/preferences', data={'default_account_id': ''}).status_code == 302
    assert user.default_account_id is None


@pytest.mark.parametrize('days', [1, 30, 60, 365])
def test_attention_window_is_personal_and_persistent(app, family, user, days):
    member = _member(family)
    client = _client(app, member)
    assert client.post('/preferences', data={
        'dashboard.attention_days': str(days),
    }).status_code == 302
    assert member.preferences['dashboard.attention_days'] == days
    assert not user.preferences
    html = client.get('/preferences').get_data(as_text=True)
    assert f'value="{days}" aria-describedby="attentionDaysHelp"' in html
    assert Settings.query.count() == 0


@pytest.mark.parametrize('value', [0, 366, True, 1.5, '', 'abc', None, [], {}])
def test_invalid_attention_windows_return_explicit_error(app, user, value):
    response = _client(app, user).post('/preferences/save', json={
        'key': 'dashboard.attention_days', 'value': value,
    })
    assert response.status_code == 400
    assert response.get_json()['error']
    assert not user.preferences


def test_invalid_attention_form_retains_input_and_does_not_save(app, user):
    client = _client(app, user)
    user.preferences = {'dashboard.attention_days': 30}
    db.session.commit()
    response = client.post('/preferences', data={'dashboard.attention_days': '366'})
    assert response.status_code == 200
    assert b'Reminder window must be between 1 and 365 days.' in response.data
    assert b'value="366" aria-describedby="attentionDaysHelp"' in response.data
    assert user.preferences == {'dashboard.attention_days': 30}


def test_saving_other_preferences_keeps_existing_attention_window(app, user):
    user.preferences = {'dashboard.attention_days': 90}
    db.session.commit()
    client = _client(app, user)
    assert client.post('/preferences', data={}).status_code == 302
    assert user.preferences['dashboard.attention_days'] == 90
    assert client.post('/preferences/save', json={
        'key': 'dashboard.attention_days', 'value': 120,
    }).status_code == 200
    assert user.preferences['dashboard.attention_days'] == 120


def test_dashboard_consumes_personal_not_household_display_preferences(app, family, user):
    db.session.add(Account(
        family_id=family.id, name='Current', account_type='Current', is_active=True,
    ))
    user.preferences = {
        'dashboard.networth_expanded': False,
        'dashboard.payday_expanded': False,
    }
    db.session.add(Settings(
        family_id=family.id, key='dashboard.networth_expanded',
        value='True', setting_type='boolean',
    ))
    db.session.commit()
    client = _client(app, user)
    with client:
        response = client.get('/')
        assert response.status_code == 200
        assert PreferenceService.get_value('dashboard.networth_expanded') is False
        assert PreferenceService.get_value('dashboard.quick_nav_expanded') is True
    html = response.get_data(as_text=True)
    assert 'id="networthCollapse" class="collapse ">' in html
    assert 'id="paydayCollapse" class="collapse ">' in html
    assert 'id="quickNavCollapse" class="collapse show">' in html
    assert 'href="/settings/modules/household"' in html


def test_unknown_settings_section_is_not_found(app, user):
    client = _client(app, user)
    assert client.get('/settings/modules/missing').status_code == 404
    assert client.post('/settings/modules/missing').status_code == 404


def test_saving_preferences_does_not_change_household_rules(app, family, user):
    db.session.add(Settings(family_id=family.id, key='payday_day', value='17', setting_type='int'))
    db.session.commit()
    client = _client(app, user)
    response = client.post('/preferences', data={
        'dashboard.networth_expanded': '1',
        'vendors.collapse_all_default': '1',
        'default_account_id': '',
        'payday_day': '25',
    })
    assert response.status_code == 302
    assert user.preferences['dashboard.networth_expanded'] is True
    assert user.preferences['dashboard.payday_expanded'] is False
    assert user.preferences['vendors.collapse_all_default'] is True
    assert Settings.query.filter_by(key='payday_day').one().value == '17'


@pytest.mark.parametrize('field', [
    'default_account_id', 'expense_reimburse_account', 'expense_payment_account',
])
@pytest.mark.parametrize('private', [False, True])
def test_account_settings_reject_other_family_or_private_accounts(
    app, family, user, field, private,
):
    other_family = Family(name='Other')
    db.session.add(other_family)
    db.session.flush()
    other_user = User(
        email='other@example.com', name='Other', family_id=family.id if private else other_family.id,
        role='member', password_hash='unused',
    )
    db.session.add(other_user)
    db.session.flush()
    account = Account(
        name='Hidden account', account_type='Current', is_active=True,
        family_id=other_user.family_id, owner_id=other_user.id if private else None,
    )
    db.session.add(account)
    db.session.commit()
    client = _client(app, user)
    path = '/preferences' if field == 'default_account_id' else '/settings/modules/expenses'
    response = client.post(path, data={
        field: str(account.id), 'expense_period_mode': 'calendar_month',
        'expense_cutoff_day': '0', 'expense_reimburse_day': '0',
    })
    assert response.status_code == 200
    assert 'you can access' in response.get_data(as_text=True)
    assert user.default_account_id is None
    assert not user.preferences
    assert Settings.query.count() == 0
    assert 'Hidden account' not in client.get(path).get_data(as_text=True)


@pytest.mark.parametrize('model, field, values', [
    (Category, 'expense_reimburse_category', {
        'name': 'Hidden category', 'head_budget': 'Hidden', 'sub_budget': 'Category',
        'category_type': 'Expense',
    }),
    (Vendor, 'expense_reimburse_vendor', {'name': 'Hidden vendor'}),
])
def test_expense_settings_reject_other_family_references(app, user, model, field, values):
    other_family = Family(name='Other')
    db.session.add(other_family)
    db.session.flush()
    record = model(family_id=other_family.id, **values)
    db.session.add(record)
    db.session.commit()
    response = _client(app, user).post('/settings/modules/expenses', data={
        field: str(record.id), 'expense_period_mode': 'calendar_month',
        'expense_cutoff_day': '0', 'expense_reimburse_day': '0',
    })
    assert response.status_code == 200
    assert 'you can access' in response.get_data(as_text=True)
    assert Settings.query.count() == 0


def test_inactive_account_cannot_be_a_personal_default(app, family, user):
    account = Account(family_id=family.id, name='Closed', account_type='Current', is_active=False)
    db.session.add(account)
    db.session.commit()
    client = _client(app, user)
    response = client.post('/preferences', data={'default_account_id': str(account.id)})
    assert response.status_code == 200
    assert 'active account you can access' in response.get_data(as_text=True)
    assert user.default_account_id is None


@pytest.mark.parametrize('section, data, key, value', [
    ('household', {'payday_day': '31'}, 'payday_day', 31),
    ('credit-cards', {'default_generation_years': '50'}, 'default_generation_years', 50),
    ('networth', {'networth_start_date': '2020-02-29'}, 'networth.start_date', '2020-02-29'),
    ('expenses', {
        'expense_period_mode': 'payday_period', 'expense_cutoff_day': '28',
        'expense_reimburse_day': '0', 'expense_auto_sync': '1',
    }, 'expenses.auto_sync', True),
])
def test_section_save_only_changes_its_own_settings(app, family, user, section, data, key, value):
    db.session.add(Settings(family_id=family.id, key='unrelated', value='keep'))
    user.preferences = {'dashboard.networth_expanded': False}
    db.session.commit()
    client = _client(app, user)
    response = client.post(f'/settings/modules/{section}', data={
        **data, 'dashboard.networth_expanded': '1', 'unrelated': 'overwrite',
    })
    assert response.status_code == 302
    with client:
        client.get('/settings')
        assert Settings.get_value(key) == value
    assert Settings.query.filter_by(key='unrelated').one().value == 'keep'
    assert user.preferences == {'dashboard.networth_expanded': False}


@pytest.mark.parametrize('section, data', [
    ('household', {'payday_day': '0'}),
    ('household', {'payday_day': '32'}),
    ('household', {'payday_day': 'abc'}),
    ('credit-cards', {'default_generation_years': '0'}),
    ('credit-cards', {'default_generation_years': '51'}),
    ('networth', {'networth_start_date': '2026-02-30'}),
    ('networth', {'networth_start_date': '20260101'}),
    ('expenses', {'expense_period_mode': 'invalid'}),
    ('expenses', {'expense_period_mode': 'calendar_month', 'expense_cutoff_day': '29'}),
    ('expenses', {
        'expense_period_mode': 'calendar_month', 'expense_cutoff_day': '15',
        'expense_reimburse_day': '29',
    }),
])
def test_invalid_section_does_not_partially_save(app, user, section, data):
    response = _client(app, user).post(f'/settings/modules/{section}', data=data)
    assert response.status_code == 200
    assert 'alert-danger' in response.get_data(as_text=True)
    assert Settings.query.count() == 0


def test_blank_optional_settings_clear_existing_values(app, family, user):
    for key, value, setting_type in (
        ('networth.start_date', '2020-01-01', 'date'),
        ('expenses.reimburse_account_id', '123', 'int'),
        ('expenses.payment_account_id', '123', 'int'),
        ('expenses.reimburse_category_id', '123', 'int'),
        ('expenses.reimburse_vendor_id', '123', 'int'),
    ):
        db.session.add(Settings(family_id=family.id, key=key, value=value, setting_type=setting_type))
    db.session.commit()
    client = _client(app, user)
    assert client.post('/settings/modules/networth', data={'networth_start_date': ''}).status_code == 302
    assert client.post('/settings/modules/expenses', data={
        'expense_period_mode': 'calendar_month', 'expense_cutoff_day': '0',
        'expense_reimburse_day': '0',
    }).status_code == 302
    assert Settings.query.filter(Settings.key.in_([
        'networth.start_date', 'expenses.reimburse_account_id', 'expenses.payment_account_id',
        'expenses.reimburse_category_id', 'expenses.reimburse_vendor_id',
    ])).count() == 0
    assert Settings.query.filter_by(key='expenses.auto_sync').one().value == 'False'


def test_legacy_combined_form_cannot_reset_unrelated_settings(app, family, user):
    db.session.add(Settings(family_id=family.id, key='payday_day', value='17', setting_type='int'))
    db.session.commit()
    response = _client(app, user).post('/settings/update', data={'payday_day': '25'})
    assert response.status_code == 302
    assert Settings.query.filter_by(key='payday_day').one().value == '17'


def test_legacy_bool_settings_are_read_as_booleans(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    Settings.set_value('expenses.auto_sync', False, setting_type='bool')
    assert Settings.get_value('expenses.auto_sync') is False


def test_preference_migration_preserves_household_defaults_without_cross_family_leakage():
    migration_path = Path(__file__).resolve().parents[1] / 'migrations' / 'versions' / 'f2a4c6e8b0d1_user_preferences.py'
    spec = importlib.util.spec_from_file_location('preferences_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE users (id INTEGER PRIMARY KEY, family_id INTEGER)')
        connection.exec_driver_sql('CREATE TABLE settings (family_id INTEGER, key TEXT, value TEXT)')
        connection.exec_driver_sql('INSERT INTO users VALUES (1, 10), (2, 10), (3, 20), (4, NULL)')
        connection.exec_driver_sql(
            "INSERT INTO settings VALUES (10, 'dashboard.networth_expanded', 'False'), "
            "(20, 'dashboard.networth_expanded', 'True'), "
            "(NULL, 'vendors.collapse_all_default', 'True'), "
            "(10, 'payday_day', '20')"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        users = sa.table('users', sa.column('id'), sa.column('preferences', sa.JSON()))
        values = dict(connection.execute(sa.select(users.c.id, users.c.preferences)).all())
        assert values == {
            1: {'dashboard.networth_expanded': False},
            2: {'dashboard.networth_expanded': False},
            3: {'dashboard.networth_expanded': True},
            4: {},
        }
        assert connection.exec_driver_sql('SELECT COUNT(*) FROM settings').scalar_one() == 4
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert 'preferences' not in {column['name'] for column in sa.inspect(connection).get_columns('users')}
    engine.dispose()
