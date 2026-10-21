import pytest
from flask import g, has_request_context, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family
from models.users import User
from services.platform.preference_service import PreferenceService
from tests.auth_helpers import login_client
from tests.test_account_security import enable_two_factor_admin


def client_for(app, user):
    client = app.test_client()
    login_client(client, user.id)
    return client


def test_appearance_context_without_request_uses_defaults(app, user):
    user.preferences = {'appearance.palette': 'purple', 'appearance.mode': 'dark'}
    db.session.commit()
    assert not has_request_context()

    rendered = render_template_string('{{ appearance.palette }}:{{ appearance.mode }}')

    assert rendered == 'blue:light'
    assert user.preferences == {'appearance.palette': 'purple', 'appearance.mode': 'dark'}


@pytest.mark.parametrize('palette', PreferenceService.PALETTES)
@pytest.mark.parametrize('mode', PreferenceService.MODES)
def test_appearance_saved_atomically_and_rendered_in_new_session(app, user, palette, mode):
    user.preferences = {'dashboard.attention_days': 90}
    db.session.commit()
    response = client_for(app, user).post('/preferences/appearance', json={
        'palette': palette, 'mode': mode,
    })
    assert response.status_code == 200
    assert response.get_json() == {'success': True}
    db.session.refresh(user)
    assert user.preferences == {
        'dashboard.attention_days': 90, 'appearance.palette': palette, 'appearance.mode': mode,
    }
    html = client_for(app, user).get('/preferences').get_data(as_text=True)
    assert f'data-palette="{palette}"' in html
    assert f'data-mode="{mode}"' in html
    assert 'data-account="true"' in html
    assert f'id="palette-{palette}" value="{palette}" checked' in html
    assert f'id="theme-{mode}" value="{mode}" checked' in html


@pytest.mark.parametrize('payload', [
    {}, [], 'blue', {'mode': 'dark'}, {'palette': 'blue'},
    {'palette': 'invalid', 'mode': 'light'},
    {'palette': ['blue'], 'mode': 'light'},
    {'palette': 'blue', 'mode': False},
    {'palette': 'blue', 'mode': 'system'},
    {'palette': None, 'mode': 'dark'},
])
def test_invalid_appearance_cannot_partially_change_preferences(app, user, payload):
    user.preferences = {'appearance.mode': 'auto', 'appearance.palette': 'purple'}
    db.session.commit()
    response = client_for(app, user).post('/preferences/appearance', json=payload)
    assert response.status_code == 400
    assert response.get_json()['error']
    assert response.get_json()['success'] is False
    assert user.preferences == {'appearance.mode': 'auto', 'appearance.palette': 'purple'}


def test_appearance_form_works_without_javascript(app, user):
    client = client_for(app, user)
    response = client.post('/preferences/appearance', data={'palette': 'graphite', 'mode': 'dark'})
    assert response.status_code == 302
    assert response.location.endswith('/preferences#appearance-card')
    assert user.preferences == {'appearance.palette': 'graphite', 'appearance.mode': 'dark'}
    html = client.get('/preferences').get_data(as_text=True)
    assert 'Your appearance has been saved to your account.' in html
    response = client.post('/preferences/appearance', data={'palette': 'nope', 'mode': 'light'}, follow_redirects=True)
    assert b'Choose a supported appearance palette.' in response.data
    assert user.preferences['appearance.mode'] == 'dark'


@pytest.mark.parametrize('same_household', [True, False])
def test_appearance_is_personal_even_for_members(app, family, user, same_household):
    if not same_household:
        family = Family(name='Another household')
        db.session.add(family)
        db.session.flush()
    member = User(email='member@example.com', name='Member', role='member', family_id=family.id)
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()
    response = client_for(app, member).post('/preferences/appearance', json={
        'palette': 'pink', 'mode': 'auto', 'user_id': user.id,
    })
    assert response.status_code == 200
    assert not user.preferences
    html = client_for(app, user).get('/preferences').get_data(as_text=True)
    assert 'data-mode="light" data-palette="blue"' in html
    assert member.preferences == {'appearance.palette': 'pink', 'appearance.mode': 'auto'}


def test_appearance_write_failure_rolls_back_and_reports_error(app, user, monkeypatch):
    client = client_for(app, user)
    def fail():
        raise SQLAlchemyError('Test write failure')
    monkeypatch.setattr(db.session, 'commit', fail)
    response = client.post('/preferences/appearance', json={'palette': 'pink', 'mode': 'dark'})
    assert response.status_code == 500
    assert response.get_json()['success'] is False
    assert 'Unable to save' in response.get_json()['error']
    assert not user.preferences


def test_appearance_requires_login_and_public_defaults_are_blue(app):
    g.pop('_login_user', None)
    client = app.test_client()
    assert client.post('/preferences/appearance', json={'palette': 'blue', 'mode': 'dark'}).status_code == 302
    response = client.get('/login')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-account="false"' in html
    assert 'data-mode="light" data-palette="blue"' in html


def test_other_preference_saves_preserve_appearance(app, user):
    client = client_for(app, user)
    client.post('/preferences/appearance', json={'palette': 'sky', 'mode': 'auto'})
    response = client.post('/preferences', data={'dashboard.attention_days': '120'})
    assert response.status_code == 302
    response = client.post('/preferences/save', json={
        'key': 'vendors.collapse_all_default', 'value': True,
    })
    assert response.status_code == 200
    assert user.preferences['appearance.palette'] == 'sky'
    assert user.preferences['appearance.mode'] == 'auto'
    assert user.preferences['dashboard.attention_days'] == 120
    assert user.preferences['vendors.collapse_all_default'] is True


def test_appearance_requires_csrf_token(app, user, monkeypatch):
    client = client_for(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    response = client.post('/preferences/appearance', json={'palette': 'blue', 'mode': 'dark'})
    assert response.status_code == 400
    assert not user.preferences


def test_operator_pages_share_the_saved_appearance(app, user):
    enable_two_factor_admin(user)
    user.preferences = {'appearance.palette': 'purple', 'appearance.mode': 'dark'}
    db.session.commit()
    client = client_for(app, user)
    for path in ('/site-admin/', '/site-admin/console/'):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'data-mode="dark" data-palette="purple"' in html
        assert 'data-account="true"' in html
