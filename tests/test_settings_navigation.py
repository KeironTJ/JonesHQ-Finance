import pytest

from extensions import db
from tests.auth_helpers import login_client


@pytest.mark.parametrize('path, active', [
    ('/help', False),
    ('/settings', True),
    ('/settings/tax', True),
])
def test_settings_link_is_in_household_profile_menu(app, user, path, active):
    client = app.test_client()
    login_client(client, user.id)

    response = client.get(path)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    primary_nav = html.split('<ul class="navbar-nav me-auto">', 1)[1].split(
        '<ul class="navbar-nav align-items-lg-center gap-1">', 1,
    )[0]
    profile_menu = html.split(
        '<ul class="dropdown-menu dropdown-menu-end">', 1,
    )[1].split('</ul>', 1)[0]
    household_menu = profile_menu.split('Your household', 1)[1].split(
        'Your account', 1,
    )[0]

    assert 'href="/settings"' not in primary_nav
    assert profile_menu.count('href="/settings"') == 1
    assert 'href="/settings"' in household_menu
    settings_link = household_menu.split('href="/settings"', 1)
    link_classes = settings_link[0].rsplit('<a class="', 1)[1].split('"', 1)[0]
    assert ('active' in link_classes.split()) is active
    assert ('aria-current="page"' in settings_link[1].split('>', 1)[0]) is active
    profile_toggle = html.split(
        '<ul class="dropdown-menu dropdown-menu-end">', 1,
    )[0].rsplit('<a class="', 1)[1].split('"', 1)[0]
    assert ('active' in profile_toggle.split()) is active


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
