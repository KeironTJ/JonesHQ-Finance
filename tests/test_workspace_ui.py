from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pytest
from flask import g

from extensions import db
from tests.auth_helpers import login_client


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_sidebar = False
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'aside' and attrs.get('id') == 'workspaceNav':
            self.in_sidebar = True
        if self.in_sidebar and tag == 'a' and 'data-nav-search' in attrs:
            self.links.append(attrs)

    def handle_endtag(self, tag):
        if tag == 'aside':
            self.in_sidebar = False


class QuickNavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif attrs.get('id') == 'quickNavCollapse':
                self.depth = 1
        elif self.depth and tag == 'a':
            self.links.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if tag == 'div' and self.depth:
            self.depth -= 1


@pytest.mark.parametrize('path', [
    '/hub', '/dashboard', '/accounts', '/transactions', '/transactions/create',
    '/transactions/subscriptions', '/transactions/consolidated',
    '/income', '/credit-cards', '/loans/', '/mortgage', '/pensions',
    '/networth', '/vehicles', '/childcare', '/plans', '/expenses',
    '/categories/', '/vendors/', '/family/', '/preferences', '/settings',
])
def test_workspace_pages_render_shared_shell(app, user, path):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="workspace"' in html
    assert 'href="#main-content"' in html
    assert 'id="workspaceNav"' in html
    assert 'id="navigationSearchInput"' in html
    assert '/static/js/workspace.js' in html
    assert '/static/css/theme.css' in html


@pytest.mark.parametrize('path, active_href', [('/hub', '/hub'), ('/dashboard', '/dashboard')])
def test_workspace_navigation_distinguishes_hub_and_finance(app, user, path, active_href):
    client = app.test_client()
    login_client(client, user.id)
    parser = NavigationParser()
    parser.feed(client.get(path).get_data(as_text=True))
    assert [link['href'] for link in parser.links if link.get('aria-current') == 'page'] == [active_href]


def test_navigation_search_source_respects_member_permissions(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts", "transactions"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    parser = NavigationParser()
    parser.feed(client.get('/accounts').get_data(as_text=True))
    hrefs = {link['href'] for link in parser.links}
    assert {'/accounts', '/transactions', '/transactions/subscriptions'} <= hrefs
    assert not {'/settings', '/family/', '/income', '/credit-cards', '/site-admin/'} & hrefs
    assert '/hub/settings' in hrefs


def test_finance_dashboard_shortcuts_respect_member_permissions(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts", "transactions", "expenses"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    parser = QuickNavigationParser()
    parser.feed(client.get('/dashboard').get_data(as_text=True))
    assert set(parser.links) == {
        '/transactions', '/accounts', '/expenses', '/hub/settings/finance',
    }


def test_workspace_navigation_switches_between_central_and_finance(app, user):
    client = app.test_client()
    login_client(client, user.id)
    for path, target in [('/hub', '/dashboard'), ('/dashboard', '/hub')]:
        parser = NavigationParser()
        parser.feed(client.get(path).get_data(as_text=True))
        assert target in {link['href'] for link in parser.links}


def test_central_hub_modules_come_from_platform_registry(app, user):
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/hub').get_data(as_text=True)
    assert 'Your modules' in html
    assert 'Open Finance' in html
    assert 'Household Hub' in html
    assert 'Organise household life with shared meals, activities and tasks.' in html
    assert 'Open Household Hub' in html
    assert 'No features or records from the other application have been imported.' not in html


def test_central_hub_uses_membership_instead_of_legacy_family_field(app, user):
    from models.family import Family, HouseholdMembership
    from services.household.membership_service import HouseholdMembershipService

    second_family = Family(name='Second Household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id, family_id=second_family.id, role='member',
        allowed_sections='["accounts"]',
    ))
    user.family_id = None
    user.role = 'member'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    with client.session_transaction() as browser_session:
        browser_session[HouseholdMembershipService.SESSION_KEY] = second_family.id

    html = client.get('/hub').get_data(as_text=True)

    assert 'Household required' not in html
    assert 'Open Finance' in html
    parser = NavigationParser()
    parser.feed(html)
    assert '/dashboard' in {link['href'] for link in parser.links}


@pytest.mark.parametrize('role', ['admin', 'member'])
def test_dashboard_settings_shortcut_uses_grouped_settings(app, user, role):
    user.role = role
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    parser = QuickNavigationParser()
    parser.feed(client.get('/dashboard').get_data(as_text=True))
    assert '/hub/settings/finance' in parser.links
    assert '/settings' not in parser.links
    assert '/preferences/finance' not in parser.links
    assert client.get('/hub/settings/finance').status_code == 200


def test_public_shell_has_no_household_navigation(app):
    g.pop('_login_user', None)
    response = app.test_client().get('/login')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'class="public-layout"' in html
    assert 'id="workspaceNav"' not in html
    assert 'id="navigationSearch"' not in html
    assert 'data-password-toggle' in html
    assert html.index('/static/js/theme-init.js') < html.index('/static/css/theme.css')


def test_all_templates_compile(app):
    for name in app.jinja_env.list_templates():
        app.jinja_env.get_template(name)


def test_design_system_stylesheets_are_local_and_present(app):
    client = app.test_client()
    g.pop('_login_user', None)
    html = client.get('/login').get_data(as_text=True)
    stylesheets = re.findall(r'href="(/static/css/[^"]+)"', html)
    assert len(stylesheets) == 6
    for stylesheet in stylesheets:
        assert client.get(stylesheet).status_code == 200


def test_shared_metric_escapes_content_and_preserves_values(app):
    template = app.jinja_env.from_string(
        "{% from 'shared/_ui.html' import metric %}"
        "{{ metric(label, value, 'bank', caption='Paid transactions only') }}"
    )
    html = template.render(label='<script>unsafe</script>', value='£12,345.67')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '£12,345.67' in html
    assert 'Paid transactions only' in html


@pytest.mark.parametrize('path, active_href', [
    ('/transactions/create', '/transactions'),
    ('/transactions/subscriptions', '/transactions/subscriptions'),
    ('/transactions/consolidated', '/transactions/consolidated'),
])
def test_transaction_navigation_selects_only_the_relevant_page(app, user, path, active_href):
    client = app.test_client()
    login_client(client, user.id)
    parser = NavigationParser()
    parser.feed(client.get(path).get_data(as_text=True))
    active = [link['href'] for link in parser.links if link.get('aria-current') == 'page']
    assert active == [active_href]


def test_shared_analytics_payload_cannot_end_script_tag(app):
    payload = {
        'labels': ['</script><script>alert(1)</script>'],
        'income_datasets': [{'label': 'Salary', 'data': [1234.56]}],
        'expense_datasets': [{'label': 'Bills', 'data': [234.56]}],
    }
    with app.test_request_context():
        html = app.jinja_env.get_template('shared/_analytics_chart.html').render(
            chart_canvas_id='categorySpendChart', chart_payload=json.dumps(payload),
        )
    assert '</script><script>alert(1)</script>' not in html
    assert r'\u003c/script\u003e' in html
    assert '1234.56' in html
    assert '234.56' in html


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('palette', ['blue', 'graphite', 'green', 'pink', 'sky', 'purple'])
@pytest.mark.parametrize('foreground, background', [
    ('text-primary', 'bg-surface'),
    ('text-secondary', 'bg-surface'),
    ('text-muted', 'bg-page'),
    ('text-muted', 'brand-soft'),
    ('action-text', 'brand'),
    ('brand', 'brand-soft'),
    ('clr-success', 'clr-success-bg'),
    ('clr-info', 'clr-info-bg'),
    ('clr-warning', 'clr-warning-bg'),
    ('clr-danger', 'clr-danger-bg'),
    ('nav-ink', 'nav-active'),
    ('nav-text', 'nav-bg'),
])
def test_theme_text_pairs_meet_wcag_aa_contrast(app, theme, palette, foreground, background):
    source = (Path(app.static_folder) / 'css' / 'system' / 'tokens.css').read_text()
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    pattern = r'--([\w-]+):\s*(#[\da-fA-F]{6});'
    tokens = {}
    for selectors, body in re.findall(r'([^{}]+)\{([^{}]*)\}', source):
        for selector in selectors.split(','):
            selector = selector.strip()
            if ' [data-palette' in selector:
                continue  # Nested selectors style the preview cards, not the root.
            if '[data-theme="dark"]' in selector and theme != 'dark':
                continue
            if ':not([data-palette="green"])' in selector:
                if palette == 'green':
                    continue
            else:
                selected = re.search(r'\[data-palette="(\w+)"\]', selector)
                if selected and selected[1] != palette:
                    continue
            tokens.update(re.findall(pattern, body))
            break

    def luminance(colour):
        channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    first, second = sorted([luminance(tokens[foreground]), luminance(tokens[background])])
    ratio = (second + 0.05) / (first + 0.05)
    assert ratio >= 4.5, (theme, palette, foreground, background, ratio)
