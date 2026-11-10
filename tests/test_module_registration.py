import ast
from pathlib import Path

from flask import Flask, url_for

from blueprints.core import register_blueprints
from services.platform.module_registry import ModuleRegistry
from tests.auth_helpers import login_client


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
    assert set(owners) == finance_blueprints
    assert {module['key'] for module in owners.values()} == {'finance'}
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
