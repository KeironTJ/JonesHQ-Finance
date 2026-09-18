import json

import pytest

from extensions import db
from models.family import Family, FamilyInvite
from models.family_assignment_labels import FamilyAssignmentLabel
from models.users import User
from services.household.family_service import FamilyService


def test_assignment_label_creation_is_ordered_and_unique(app, family):
    first = FamilyService.create_assignment_label(family.id, 'Child')
    duplicate = FamilyService.create_assignment_label(family.id, 'Child')
    second = FamilyService.create_assignment_label(family.id, 'Parent')

    assert first.sort_order == 1
    assert duplicate is None
    assert second.sort_order == 2
    assert FamilyAssignmentLabel.query.count() == 2


def test_invite_serializes_member_sections_and_can_be_revoked(app, family, user):
    invite = FamilyService.create_invite(
        family.id,
        user.id,
        'New Member',
        'member',
        ['income', 'accounts', 'income'],
    )

    assert json.loads(invite.allowed_sections) == ['accounts', 'income']
    FamilyService.revoke_invite(invite.id, family.id)
    assert db.session.get(FamilyInvite, invite.id) is None


def test_update_and_remove_member(app, family, user):
    member = User(
        email='member2@example.com',
        name='Member Two',
        family_id=family.id,
        role='member',
    )
    member.set_password('TestPass1!')
    db.session.add(member)
    db.session.commit()

    updated = FamilyService.update_member(
        member.id,
        family.id,
        user.id,
        'member',
        'Updated Member',
        ['income', 'accounts'],
    )

    assert updated.member_name == 'Updated Member'
    assert updated.get_allowed_sections() == {'accounts', 'income'}

    removed_name = FamilyService.remove_member(member.id, family.id, user.id)

    assert removed_name == 'Member Two'
    assert db.session.get(User, member.id).family_id is None
