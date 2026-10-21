import pytest

from extensions import db
from tests.auth_helpers import login_client


@pytest.mark.parametrize('path, active', [
    ('/help', False),
    ('/settings', True),
    ('/settings/tax', True),
])
def test_settings_link_is_in_workspace_navigation(app, user, path, active):
    client = app.test_client()
    login_client(client, user.id)

    response = client.get(path)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    navigation = html.split('id="workspaceNav"', 1)[1].split('</aside>', 1)[0]
    assert navigation.count('href="/settings"') == 1
    settings_link = navigation.split('href="/settings"', 1)
    link_classes = settings_link[0].rsplit('<a class="', 1)[1].split('"', 1)[0]
    assert ('active' in link_classes.split()) is active
    assert ('aria-current="page"' in settings_link[1].split('>', 1)[0]) is active


def test_settings_remains_hidden_and_forbidden_for_members(app, user):
    user.role = 'member'
    user.allowed_sections = '["settings"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.get('/help')

    assert response.status_code == 200
    assert 'href="/settings"' not in response.get_data(as_text=True)
    assert client.get('/settings').status_code == 403
