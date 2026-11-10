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
    assert not any(rule.rule == '/dashboard' for rule in core_app.url_map.iter_rules())


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


def test_finance_entry_points_keep_existing_urls(app):
    with app.test_request_context():
        assert url_for('dashboard.index') == '/dashboard'
        assert url_for('finance_preferences.index') == '/preferences/finance'
        assert url_for('finance_preferences.save_preference') == '/preferences/save'
        assert url_for('settings.overview') == '/hub/settings/finance'
        assert ModuleRegistry.module_for_blueprint('finance_preferences')['key'] == 'finance'
        assert ModuleRegistry.module_for_blueprint('preferences') is None


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


def test_finance_owns_legacy_preference_post_but_not_appearance(app, user):
    adapter = app.url_map.bind('localhost')
    assert adapter.match('/preferences', method='GET')[0] == 'preferences.index'
    assert adapter.match('/preferences', method='POST')[0] == 'finance_preferences.index'
    assert adapter.match('/preferences/appearance', method='POST')[0] == 'preferences.appearance'
    client = app.test_client()
    login_client(client, user.id)
    for path in ('/preferences/finance', '/hub/settings/finance'):
        assert client.get(path).status_code == 200
    assert client.get('/income').status_code == 200


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
    html = client.get('/accounts').get_data(as_text=True)
    assert '<strong id="workspaceNavLabel">Example module</strong>' in html
    assert 'Example overview' in html
    assert 'Example guide' in html
    sidebar = NavigationParser()
    sidebar.feed(html)
    hrefs = {link['href'] for link in sidebar.links}
    assert '/transactions' not in hrefs
    assert '/account/security' in hrefs
    assert '/dashboard' in hrefs
    assert '/accounts' in hrefs
    central = client.get('/hub').get_data(as_text=True)
    assert 'Open Example module' in central


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
    client.post('/family/select', data={'family_id': second_family.id})
    for path in ('/accounts', '/transactions/subscriptions', '/hub/settings/finance'):
        html = client.get(path).get_data(as_text=True)
        sidebar = NavigationParser()
        sidebar.feed(html)
        hrefs = {link['href'] for link in sidebar.links}
        assert {'/accounts', '/transactions', '/transactions/subscriptions'} <= hrefs
        assert not {'/income', '/vendors/', '/settings', '/family/'} & hrefs
        assert len([link for link in sidebar.links if link.get('aria-current') == 'page']) == 1
