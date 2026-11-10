import ast
from pathlib import Path

from flask import Flask, url_for
from jinja2 import ChoiceLoader, DictLoader

from blueprints.core import register_blueprints
from extensions import db
from models.family import Family, HouseholdMembership
from services.platform.module_registry import ModuleRegistry
from services.platform import module_registry
from tests.auth_helpers import login_client
from tests.test_workspace_ui import NavigationParser


def test_core_registers_without_finance_blueprints(app):
    core_app = Flask('core-registration')
    register_blueprints(core_app)

    assert set(core_app.blueprints) == {
        'auth', 'central', 'family', 'preferences', 'site_admin',
    }
    assert not any(rule.rule == '/finance/dashboard' for rule in core_app.url_map.iter_rules())


def test_registry_owns_every_finance_blueprint(app):
    owners = app.extensions['platform_modules']
    finance_blueprints = {
        name for name, blueprint in app.blueprints.items()
        if blueprint.import_name.startswith('blueprints.finance.')
    }
    assert finance_blueprints
    assert {name for name, module in owners.items() if module['key'] == 'finance'} == finance_blueprints
    assert {module['key'] for module in owners.values()} == {'finance', 'household'}
    assert owners['household']['home_endpoint'] == 'household.calendar'
    assert not {'auth', 'central', 'family', 'preferences', 'site_admin'} & set(owners)


def test_module_entry_points_use_workspace_namespaces(app):
    with app.test_request_context():
        assert url_for('central.hub') == '/central/'
        assert url_for('central.settings') == '/central/settings'
        assert url_for('family.index') == '/central/family/'
        assert url_for('preferences.index') == '/central/preferences'
        assert url_for('auth.account_security') == '/central/account/security'
        assert url_for('dashboard.index') == '/finance/dashboard'
        assert url_for('finance_preferences.index') == '/finance/preferences'
        assert url_for('finance_preferences.save_preference') == '/finance/preferences/save'
        assert url_for('settings.overview') == '/finance/settings/overview'
        assert ModuleRegistry.module_for_blueprint('finance_preferences')['key'] == 'finance'
        assert ModuleRegistry.module_for_blueprint('preferences') is None


def test_workspace_pages_are_not_exposed_at_legacy_root_paths(app):
    registered_paths = {rule.rule for rule in app.url_map.iter_rules()}
    assert not {'/hub', '/dashboard', '/accounts', '/family/'} & registered_paths


def test_core_preferences_have_no_finance_implementation_imports(app):
    root = Path(app.root_path)
    for relative in (
        Path('blueprints') / 'core' / 'preferences' / 'routes.py',
        Path('services') / 'platform' / 'preference_service.py',
    ):
        tree = ast.parse((root / relative).read_text(encoding='utf-8'))
        imports = [
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(
            name.startswith(('blueprints.finance', 'services.finance', 'models.accounts'))
            for name in imports
        )


def test_finance_and_central_preferences_have_distinct_routes(app, user):
    adapter = app.url_map.bind('localhost')
    assert adapter.match('/central/preferences', method='GET')[0] == 'preferences.index'
    assert adapter.match('/finance/preferences', method='POST')[0] == 'finance_preferences.index'
    assert adapter.match('/central/preferences/appearance', method='POST')[0] == 'preferences.appearance'
    client = app.test_client()
    login_client(client, user.id)
    for path in ('/finance/preferences', '/finance/settings/overview'):
        assert client.get(path).status_code == 200
    assert client.get('/finance/income').status_code == 200


def test_shared_navigation_renders_module_descriptor_not_finance_defaults(app, user, monkeypatch):
    example = {
        'key': 'example', 'title': 'Example module', 'overview_label': 'Example overview',
        'icon': 'bi-calendar', 'home_endpoint': 'accounts.index',
        'navigation_template': 'example/_navigation.html', 'status': 'available',
        'requires_household': True, 'default_destination': False,
        'settings_group': lambda user: {
            'label': 'Example', 'endpoint': 'auth.account_security', 'pages': [],
        },
    }
    monkeypatch.setattr(module_registry, '_MODULES', (*module_registry._MODULES, example))
    monkeypatch.setitem(app.extensions['platform_modules'], 'accounts', example)
    membership = user.get_active_household_membership()
    membership.allowed_modules = ['finance', 'household', 'example']
    db.session.commit()
    monkeypatch.setattr(app.jinja_env, 'loader', ChoiceLoader([
        DictLoader({
            'example/_navigation.html': "{{ nav_link('auth.help', 'Example guide', 'book') }}",
        }),
        app.jinja_env.loader,
    ]))
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/finance/accounts').get_data(as_text=True)
    assert '<strong id="workspaceNavLabel">Example module</strong>' in html
    assert 'Example overview' in html
    assert 'Example guide' in html
    sidebar = NavigationParser()
    sidebar.feed(html)
    hrefs = {link['href'] for link in sidebar.links}
    assert '/finance/transactions' not in hrefs
    assert '/central/settings' in hrefs
    assert 'href="/central/account/security" data-nav-search>Example settings</a>' in html
    assert '/finance/dashboard' in hrefs
    assert '/finance/accounts' in hrefs
    central = client.get('/central/').get_data(as_text=True)
    assert 'Open Example module' in central
    settings = client.get('/central/settings').get_data(as_text=True)
    assert 'Open Example settings' in settings
    assert 'href="/central/account/security"' in settings


def test_module_navigation_permissions_follow_selected_household(app, user):
    second_family = Family(name='Restricted household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id, family_id=second_family.id, role='member',
        allowed_sections='["accounts", "transactions"]',
    ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    client.post('/central/family/select', data={'family_id': second_family.id})
    for path in ('/finance/accounts', '/finance/transactions/subscriptions', '/finance/settings/overview'):
        html = client.get(path).get_data(as_text=True)
        sidebar = NavigationParser()
        sidebar.feed(html)
        hrefs = {link['href'] for link in sidebar.links}
        assert {'/finance/accounts', '/finance/transactions', '/finance/transactions/subscriptions'} <= hrefs
        assert not {'/finance/income', '/finance/vendors/', '/finance/settings', '/central/family/'} & hrefs
        assert len([link for link in sidebar.links if link.get('aria-current') == 'page']) == 1
