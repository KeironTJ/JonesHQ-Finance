from decimal import Decimal

from extensions import db
from models.childcare import Child, ChildActivityType
from services.childcare_service import ChildcareService


def test_childcare_setup_crud_assigns_family_and_normalizes_day(app, family, monkeypatch):
    monkeypatch.setattr('services.childcare_service.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    child = ChildcareService.create_child({
        'name': 'Child One',
        'year_group': 'Nursery',
        'transaction_day': '31',
        'category_id': '',
        'vendor_id': '',
    })
    assert child.family_id == family.id
    assert child.transaction_day == 28

    updated = ChildcareService.update_child(child.id, {
        'name': 'Child Updated',
        'year_group': 'Reception',
        'transaction_day': '15',
        'category_id': '',
        'vendor_id': '',
        'is_active': 'on',
    })
    activity = ChildcareService.create_activity_type(child.id, {
        'name': 'Morning Club',
        'cost': '12.50',
        'provider': 'School',
        'occurs_monday': 'on',
    })
    deleted_name = ChildcareService.delete_child(child.id)

    assert updated.name == 'Child Updated'
    assert updated.transaction_day == 15
    assert activity.family_id == family.id
    assert activity.cost == Decimal('12.50')
    assert activity.occurs_monday is True
    assert deleted_name == 'Child Updated'
    assert db.session.get(Child, child.id) is None
    assert db.session.get(ChildActivityType, activity.id) is None


def test_update_activity_type_changes_schedule_and_delete_name(app, family, monkeypatch):
    monkeypatch.setattr('services.childcare_service.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    child = ChildcareService.create_child({'name': 'Child Two'})
    activity = ChildcareService.create_activity_type(child.id, {
        'name': 'Club',
        'cost': '10',
        'provider': 'School',
        'occurs_monday': 'on',
    })

    updated = ChildcareService.update_activity_type(activity.id, {
        'name': 'Late Club',
        'cost': '12.75',
        'provider': 'Provider',
        'is_active': 'on',
        'occurs_tuesday': 'on',
    })
    deleted_name = ChildcareService.delete_activity_type(activity.id)

    assert updated.name == 'Late Club'
    assert updated.cost == Decimal('12.75')
    assert updated.occurs_monday is False
    assert updated.occurs_tuesday is True
    assert deleted_name == 'Late Club'
