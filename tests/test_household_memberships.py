import pytest

from flask import session
from flask_login import login_user

from extensions import db
from models.accounts import Account
from models.family import Family, HouseholdMembership
from models.users import User
from services.household.membership_service import HouseholdMembershipService
from tests.auth_helpers import detach_user_from_households, login_client
from utils.db_helpers import get_family_id


@pytest.mark.parametrize('clear_default', [False, True])
def test_auto_stamp_uses_selected_household_and_preserves_explicit_ids(app, user, family, clear_default):
    second_family = Family(name='Selected Household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id, family_id=second_family.id, role='admin',
    ))
    if clear_default:
        user.family_id = None
    db.session.commit()

    with app.test_request_context('/accounts'):
        login_user(user)
        HouseholdMembershipService.select(user, second_family.id)
        implicit = Account(name='Implicit', account_type='Current')
        explicit = Account(name='Explicit', account_type='Current', family_id=family.id)
        global_record = Account(name='Global', account_type='Current')
        global_record._global_record = True
        db.session.add_all([implicit, explicit, global_record])
        db.session.flush()
        assert implicit.family_id == second_family.id
        assert explicit.family_id == family.id
        assert global_record.family_id is None


def test_auto_stamp_does_not_invent_household_without_request_or_membership(app, user):
    outside_request = Account(name='Outside request', account_type='Current')
    db.session.add(outside_request)
    db.session.flush()
    assert outside_request.family_id is None
    detach_user_from_households(user)
    with app.test_request_context('/accounts'):
        login_user(user)
        detached = Account(name='Detached', account_type='Current')
        db.session.add(detached)
        db.session.flush()
        assert detached.family_id is None


def test_legacy_user_gets_household_membership(app, user, family):
    membership = HouseholdMembership.query.filter_by(
        user_id=user.id, family_id=family.id,
    ).one()
    assert membership.role == user.role
    assert membership.member_name == user.member_name
    assert membership.allowed_sections == user.allowed_sections


def test_active_household_selection_uses_membership_permissions(app, user):
    second_family = Family(name='Second Household')
    db.session.add(second_family)
    db.session.flush()
    membership = HouseholdMembership(
        user_id=user.id,
        family_id=second_family.id,
        role='member',
        allowed_sections='["accounts"]',
    )
    db.session.add(membership)
    db.session.commit()

    with app.test_request_context('/'):
        login_user(user)
        assert get_family_id() == user.family_id
        HouseholdMembershipService.select(user, second_family.id)
        assert session[HouseholdMembershipService.SESSION_KEY] == second_family.id
        assert get_family_id() == second_family.id
        assert user.is_household_owner is False
        assert user.can_access_section('accounts') is True
        assert user.can_access_section('income') is False


def test_active_household_cannot_be_set_to_another_users_family(app, user):
    other_family = Family(name='Other Household')
    db.session.add(other_family)
    db.session.commit()

    with app.test_request_context('/'):
        login_user(user)
        with pytest.raises(ValueError, match='household you belong to'):
            HouseholdMembershipService.select(user, other_family.id)
        assert get_family_id() == user.family_id


def test_household_switcher_changes_active_context_and_is_membership_scoped(app, user):
    second_family = Family(name='Second Household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id,
        family_id=second_family.id,
        role='member',
        allowed_sections='["accounts"]',
    ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    html = client.get('/hub').get_data(as_text=True)
    assert 'id="activeHousehold"' in html
    response = client.post('/family/select', data={'family_id': second_family.id})
    assert response.status_code == 302
    assert response.location.endswith('/hub')
    response = client.post('/family/select', data={'family_id': 999999})
    assert response.status_code == 302
    assert b'Choose a household you belong to.' in client.get(response.location).data
    with client:
        client.get('/dashboard')
        assert get_family_id() == second_family.id


def test_member_can_switch_household_without_finance_owner_permission(app, user):
    user.role = 'member'
    user.allowed_sections = '["accounts"]'
    db.session.commit()
    second_family = Family(name='Second Household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id,
        family_id=second_family.id,
        role='member',
        allowed_sections='["transactions"]',
    ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.post('/family/select', data={'family_id': second_family.id})
    assert response.status_code == 302
    assert client.get('/accounts').status_code == 403
    assert client.get('/transactions').status_code == 200


def test_family_members_relationship_includes_membership(app, user, family):
    assert user in family.members.all()
    assert family in user.families


def test_household_scoped_user_lookup_uses_membership(app, user):
    second_family = Family(name='Second Household')
    db.session.add(second_family)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id,
        family_id=second_family.id,
        role='member',
        allowed_sections='["accounts"]',
    ))
    db.session.commit()

    with app.test_request_context('/'):
        login_user(user)
        HouseholdMembershipService.select(user, second_family.id)
        from utils.db_helpers import family_get, family_query
        assert family_get(type(user), user.id) is user
        assert family_query(type(user)).all() == [user]


def test_detached_member_owner_check_is_false(app, user):
    detach_user_from_households(user)
    assert user.is_household_owner is False


def test_role_and_finance_edits_use_selected_household_not_targets_default(app, user, family):
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    member = User(
        family_id=other_family.id, email='multi-member@example.test',
        name='Multi Member', role='admin', password_hash='unused',
    )
    db.session.add(member)
    db.session.flush()
    membership = HouseholdMembership(
        user_id=member.id, family_id=family.id, role='member',
        allowed_sections='["accounts"]',
    )
    db.session.add(membership)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    html = client.get('/family/').get_data(as_text=True)
    assert '<option value="member" selected>Member</option>' in html
    response = client.post(f'/settings/access/members/{member.id}', data={
        'member_name': 'Local display', 'sections': ['transactions'],
    })
    assert response.status_code == 302
    db.session.refresh(membership)
    assert membership.allowed_sections == '["transactions"]'
    assert member.role == 'admin'
    response = client.post(f'/family/members/{member.id}/role', data={'role': 'admin'})
    assert response.status_code == 302
    db.session.refresh(membership)
    assert membership.role == 'admin'
    response = client.post(f'/family/members/{member.id}/role', data={'role': 'member'})
    assert response.status_code == 302
    db.session.refresh(membership)
    assert membership.role == 'member'
    assert member.role == 'admin'
