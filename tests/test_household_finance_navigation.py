import pytest
from flask import g
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User
from tests.auth_helpers import login_client
from tests.test_account_security import make_stale, request
from tests.test_workspace_ui import NavigationParser


def member_in(family, email='member@example.com'):
    member = User(
        family_id=family.id, email=email, name='Member', role='member',
        member_name='Display', allowed_sections='["accounts"]', password_hash='unused',
    )
    db.session.add(member)
    db.session.commit()
    return member


def test_membership_and_finance_have_distinct_editors(app, family, user):
    member = member_in(family)
    label = FamilyAssignmentLabel(family_id=family.id, name='Custom child', is_active=True)
    db.session.add(label)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    central = client.get('/central/family/').get_data(as_text=True)
    assert f'action="/central/family/members/{member.id}/role"' in central
    assert f'action="/finance/settings/access/members/{member.id}"' not in central
    assert 'Custom child' not in central
    assert 'Initial Finance permissions for this invitation' in central
    finance = client.get('/finance/settings/access').get_data(as_text=True)
    assert 'Custom child' in finance
    assert f'action="/finance/settings/access/members/{member.id}"' in finance
    assert 'name="role"' not in finance
    assert 'private-record visibility' in finance
    parser = NavigationParser()
    parser.feed(finance)
    assert [link['href'] for link in parser.links if link.get('aria-current') == 'page'] == ['/central/settings']


def test_role_edit_preserves_finance_configuration_and_cannot_edit_self(app, family, user):
    member = member_in(family)
    client = app.test_client()
    login_client(client, user.id)
    for role in ('admin', 'member'):
        response = request(client, 'post', f'/central/family/members/{member.id}/role', data={
            'role': role, 'sections': ['income'], 'member_name': 'Changed',
        })
        assert response.location.endswith('/central/family/')
        assert member.role == role
        assert member.allowed_sections == '["accounts"]'
        assert member.member_name == 'Display'
    response = request(client, 'post', f'/central/family/members/{user.id}/role', data={'role': 'member'})
    assert response.status_code == 302
    assert user.role == 'admin'
    response = request(client, 'post', f'/central/family/members/{member.id}/role', data={'role': 'invalid'})
    assert response.status_code == 302
    assert member.role == 'member'


def test_finance_edit_preserves_role_and_rejects_owner_or_invalid_sections(app, family, user):
    member = member_in(family)
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'post', f'/finance/settings/access/members/{member.id}', data={
        'role': 'admin', 'member_name': 'Finance name', 'sections': ['income', 'accounts'],
    })
    assert response.location.endswith('/finance/settings/access')
    assert member.role == 'member'
    assert member.member_name == 'Finance name'
    assert member.get_allowed_sections() == {'income', 'accounts'}
    request(client, 'post', f'/finance/settings/access/members/{member.id}', data={'sections': ['settings']})
    assert member.get_allowed_sections() == {'income', 'accounts'}
    request(client, 'post', f'/finance/settings/access/members/{user.id}', data={'sections': []})
    assert user.role == 'admin'
    request(client, 'post', f'/finance/settings/access/members/{member.id}', data={})
    assert member.get_allowed_sections() == set()


def test_new_writes_are_owner_only_recent_auth_and_household_scoped(app, family, user):
    member = member_in(family)
    other = Family(name='Other')
    db.session.add(other)
    db.session.commit()
    outsider = member_in(other, 'other@example.com')
    paths = [
        f'/central/family/members/{outsider.id}/role',
        f'/finance/settings/access/members/{outsider.id}',
    ]
    client = app.test_client()
    login_client(client, user.id)
    for path in paths:
        assert request(client, 'post', path, data={'role': 'admin'}).status_code == 404
    make_stale(user)
    for path in paths:
        assert request(client, 'post', path, data={}).location.startswith('/central/account/confirm')
    login_client(client, member.id)
    assert request(client, 'get', '/finance/settings/access').status_code == 403
    for path in paths:
        assert request(client, 'post', path, data={}).status_code == 403
    g.pop('_login_user', None)
    assert app.test_client().get('/finance/settings/access').status_code == 302


def test_assignment_labels_return_to_finance_and_remain_scoped(app, family, user):
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/central/family/assignment-labels', data={'label_name': 'Child'})
    assert response.location.endswith('/finance/settings/access')
    label = FamilyAssignmentLabel.query.one()
    assert label.family_id == family.id
    response = client.post(f'/central/family/assignment-labels/{label.id}/delete')
    assert response.location.endswith('/finance/settings/access')
    assert FamilyAssignmentLabel.query.count() == 0


def test_other_owner_display_name_remains_editable_without_changing_sections(app, family, user):
    member = member_in(family)
    member.role = 'admin'
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = request(client, 'post', f'/finance/settings/access/members/{member.id}', data={
        'member_name': 'Owner display',
    })
    assert response.status_code == 302
    assert member.role == 'admin'
    assert member.member_name == 'Owner display'
    assert member.allowed_sections == '["accounts"]'


@pytest.mark.parametrize('kind', ['role', 'finance', 'label'])
def test_database_errors_are_reported_and_rolled_back(app, family, user, monkeypatch, kind):
    member = member_in(family)
    client = app.test_client()
    login_client(client, user.id)

    def fail_commit():
        raise SQLAlchemyError('Test failure')

    monkeypatch.setattr(db.session, 'commit', fail_commit)
    path, data = {
        'role': (f'/central/family/members/{member.id}/role', {'role': 'admin'}),
        'finance': (f'/finance/settings/access/members/{member.id}', {'sections': ['income']}),
        'label': ('/central/family/assignment-labels', {'label_name': 'Child'}),
    }[kind]
    response = request(client, 'post', path, data=data)
    assert response.status_code == 302
    assert member.role == 'member'
    assert member.allowed_sections == '["accounts"]'
    assert FamilyAssignmentLabel.query.count() == 0
    html = request(client, 'get', response.location).get_data(as_text=True)
    assert 'Unable to' in html
