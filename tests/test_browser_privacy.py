from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest
from flask import g

from extensions import db
from tests.auth_helpers import login_client


class AssetParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'img') and attrs.get('src'):
            self.urls.append(attrs['src'])
        if tag == 'link' and attrs.get('href'):
            self.urls.append(attrs['href'])


def assert_local_assets(client, html):
    parser = AssetParser()
    parser.feed(html)
    assert parser.urls
    for url in parser.urls:
        assert not urlsplit(url).netloc, url
        assert not urlsplit(url).scheme, url
        assert client.get(url).status_code == 200, url


def test_storage_notice_public_and_linked_from_login(app):
    g.pop('_login_user', None)
    client = app.test_client()
    response = client.get('/cookies')
    assert response.status_code == 200
    for text in (
        b'remember_token', b'jhq-theme', b'categories.openSections',
        b'vendors.openSections', b'not a complete privacy policy',
    ):
        assert text in response.data
    login = client.get('/login')
    assert b'href="/cookies"' in login.data
    assert_local_assets(client, login.get_data(as_text=True))
    assert_local_assets(client, response.get_data(as_text=True))


def test_notice_accessible_before_required_two_factor_setup(app, user):
    user.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    assert client.get('/cookies').status_code == 200
    assert client.get('/privacy').status_code == 200
    g.pop('_login_user', None)


def test_privacy_notice_public_complete_and_serves_local_assets(app):
    g.pop('_login_user', None)
    client = app.test_client()
    response = client.get('/privacy')
    assert response.status_code == 200
    assert response.mimetype == 'text/html'
    body = b' '.join(response.data.split())
    for content in (
        b'Keiron Jones', b'United Kingdom', b'mailto:keirontj@gmail.com',
        b'Resend', b'legitimate interests', b'performance of the service agreement',
        b"including everyone's private records", b'not encryption', b'no fixed retention period',
        b'Names and free text are not anonymised', b'former households',
        b'Current members retain their login accounts', b'international-transfer',
        b'Information Commissioner', b'href="/cookies"',
    ):
        assert content in body
    assert_local_assets(client, response.get_data(as_text=True))


@pytest.mark.parametrize('path', ['/login', '/register', '/cookies'])
def test_privacy_notice_linked_on_public_pages(app, path):
    g.pop('_login_user', None)
    response = app.test_client().get(path)
    assert response.status_code == 200
    assert b'href="/privacy"' in response.data


def test_privacy_notice_linked_before_family_join(app, user, family):
    from models import FamilyInvite

    invite = FamilyInvite(family_id=family.id, created_by_id=user.id, member_name='Invitee')
    db.session.add(invite)
    db.session.commit()
    g.pop('_login_user', None)
    response = app.test_client().get(f'/family/join/{invite.token}')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.index('href="/privacy"') < body.index('Create Account &amp; Join')


def test_privacy_notice_renders_configured_security_retention(app, monkeypatch):
    monkeypatch.setitem(app.config, 'SECURITY_EVENT_RETENTION_DAYS', 42)
    g.pop('_login_user', None)
    response = app.test_client().get('/privacy')
    assert b'42 days are eligible for cleanup' in response.data
    assert b'365 days' not in response.data


@pytest.mark.parametrize('path', [
    '/expenses/mileage', '/vendors/analytics', '/categories/analytics', '/networth',
])
def test_chart_pages_use_local_chart_library(app, user, path):
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(path, follow_redirects=True)
    assert response.status_code == 200
    assert b'/static/vendor/chartjs/chart.umd.min.js' in response.data
    assert_local_assets(client, response.get_data(as_text=True))
    g.pop('_login_user', None)


def test_admin_assets_are_local(app, user):
    user.is_site_admin = True
    user.totp_enabled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.totp_secret = 'JBSWY3DPEHPK3PXP'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/admin/')
    assert response.status_code == 200
    assert_local_assets(client, response.get_data(as_text=True))
    g.pop('_login_user', None)


def test_icon_fonts_resolve_and_theme_has_no_remote_import(app):
    client = app.test_client()
    css = client.get('/static/vendor/bootstrap-icons/bootstrap-icons.min.css')
    assert css.status_code == 200
    fonts = re.findall(r'url\(["\']?([^)"\']+)', css.get_data(as_text=True))
    assert len(fonts) == 2
    for font in fonts:
        response = client.get('/static/vendor/bootstrap-icons/' + font.lstrip('./'))
        assert response.status_code == 200
        assert len(response.data) > 1000
    theme = client.get('/static/css/theme.css').get_data(as_text=True)
    assert 'fonts.googleapis.com' not in theme
    assert '@import' not in theme


def test_templates_have_no_external_asset_tags(app):
    for template in Path(app.root_path, 'templates').rglob('*.html'):
        parser = AssetParser()
        parser.feed(template.read_text(encoding='utf-8'))
        assert not any(
            url.startswith(('http:', 'https:', '//')) for url in parser.urls
        ), str(template)
