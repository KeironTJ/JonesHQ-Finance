from datetime import date
from decimal import Decimal

import pytest
from flask import g

from extensions import db
from models.childcare import Child, ChildActivityType, DailyChildcareActivity
from models.family import Family
from models.accounts import Account
from models.transactions import Transaction
from models.childcare import MonthlyChildcareSummary
from models.categories import Category
from services.household.childcare_service import ChildcareService
from tests.auth_helpers import login_client


@pytest.fixture
def activity_records(family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    children = [
        Child(family_id=family.id, name='Own child'),
        Child(family_id=family.id, name='Sibling'),
        Child(family_id=other_family.id, name='Other household child'),
    ]
    db.session.add_all(children)
    db.session.flush()
    types = [
        ChildActivityType(family_id=child.family_id, child_id=child.id,
                          name='Club', cost=Decimal('12.50'))
        for child in children
    ]
    db.session.add_all(types)
    db.session.commit()
    return children, types


@pytest.mark.parametrize('child_index,type_index', [
    (2, 2), (0, 2), (2, 0), (0, 1), (None, 0), (0, None),
])
def test_daily_activity_rejects_invalid_references(activity_records, child_index, type_index):
    children, types = activity_records
    child_id = children[child_index].id if child_index is not None else -1
    type_id = types[type_index].id if type_index is not None else -1
    with pytest.raises(ValueError, match='Invalid child or activity type'):
        ChildcareService.update_daily_activity(date(2026, 1, 5), child_id, type_id, True)
    assert DailyChildcareActivity.query.count() == 0


def test_daily_activity_assigns_family_and_preserves_updates(activity_records, family):
    children, types = activity_records
    activity = ChildcareService.update_daily_activity(
        date(2026, 1, 5), children[0].id, types[0].id, True)
    assert activity.family_id == family.id
    assert activity.actual_cost == Decimal('12.50')
    updated = ChildcareService.update_daily_activity(
        date(2026, 1, 5), children[0].id, types[0].id, False, Decimal('8.25'))
    assert updated.id == activity.id
    assert updated.occurred is False
    assert updated.actual_cost == Decimal('8.25')
    assert DailyChildcareActivity.query.count() == 1


def test_daily_activity_rejects_existing_cross_household_reference(activity_records, family):
    children, types = activity_records
    activity = DailyChildcareActivity(
        family_id=family.id, date=date(2026, 1, 5),
        child_id=children[2].id, activity_type_id=types[2].id, occurred=False)
    db.session.add(activity)
    db.session.commit()
    with pytest.raises(ValueError, match='Invalid child or activity type'):
        ChildcareService.update_daily_activity(
            activity.date, activity.child_id, activity.activity_type_id, True)
    db.session.refresh(activity)
    assert activity.occurred is False


def test_daily_activity_bulk_workflows_preserve_family_scope(activity_records, family):
    children, types = activity_records
    types[0].occurs_monday = True
    db.session.commit()
    assert ChildcareService.apply_templates_to_month(2026, 1) == 4
    assert ChildcareService.copy_previous_month(2026, 2) == 4
    ChildcareService.bulk_update_week(
        date(2026, 3, 2), children[0].id, {'Monday': [types[0].id]})
    activities = DailyChildcareActivity.query.all()
    assert len(activities) == 9
    assert all(
        activity.family_id == family.id
        and activity.child_id == children[0].id
        and activity.activity_type_id == types[0].id
        for activity in activities
    )


@pytest.mark.parametrize('child_index,type_index', [(2, 2), (0, 2), (2, 0), (0, 1), (0, 0)])
def test_daily_activity_endpoint_scopes_references(app, user, activity_records, child_index, type_index):
    children, types = activity_records
    client = app.test_client()
    login_client(client, user.id)
    g.pop('_login_user', None)
    response = client.post('/childcare/update_activity', json={
        'date': '2026-01-05', 'child_id': children[child_index].id,
        'activity_type_id': types[type_index].id, 'occurred': True,
    })
    g.pop('_login_user', None)
    if child_index == type_index == 0:
        assert response.status_code == 200
        assert response.get_json() == {
            'success': True, 'daily_total': 12.5, 'monthly_total': 12.5, 'cost': 12.5,
        }
        assert DailyChildcareActivity.query.one().family_id == user.family_id
    else:
        assert response.status_code == 400
        assert response.get_json() == {
            'success': False, 'error': 'Invalid child or activity type selected.',
        }
        assert DailyChildcareActivity.query.count() == 0


def test_childcare_setup_crud_assigns_family_and_normalizes_day(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
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
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
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


def test_update_monthly_transaction_and_set_default_account(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    child = ChildcareService.create_child({'name': 'Child Three'})
    account = Account(
        family_id=family.id, name='Childcare Account', account_type='Joint',
        balance=0, is_active=True
    )
    db.session.add(account)
    db.session.flush()
    category = Category(
        family_id=family.id, name='Childcare', head_budget='Childcare',
        sub_budget='Childcare', category_type='expense'
    )
    db.session.add(category)
    db.session.flush()
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=-100, transaction_date=date(2026, 1, 28)
    )
    db.session.add(transaction)
    db.session.flush()
    summary = MonthlyChildcareSummary(
        family_id=family.id, year_month='2026-01', child_id=child.id,
        total_cost=Decimal('100'), transaction_id=transaction.id,
        account_id=account.id
    )
    db.session.add(summary)
    db.session.commit()

    updated_amount = ChildcareService.update_monthly_transaction(
        transaction.id, child.id, Decimal('125')
    )
    assigned = ChildcareService.set_default_account(child.id, account.id)

    assert updated_amount == Decimal('125')
    assert transaction.amount == Decimal('-125')
    assert summary.total_cost == Decimal('125')
    assert assigned is True
    assert child.default_account_id == account.id


def test_bulk_monthly_transactions_skips_existing_summary(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    child_one = ChildcareService.create_child({'name': 'Bulk Child One'})
    child_two = ChildcareService.create_child({'name': 'Bulk Child Two'})
    calls = []

    existing = MonthlyChildcareSummary(
        family_id=family.id, year_month='2026-01', child_id=child_one.id,
        total_cost=Decimal('10'), transaction_id=123, account_id=None
    )
    db.session.add(existing)
    db.session.commit()

    def fake_create(year, month, child_id, account_id):
        calls.append((year, month, child_id, account_id))
        return object()

    monkeypatch.setattr(
        'services.household.childcare_service.ChildcareService.create_monthly_transaction',
        staticmethod(fake_create),
    )
    created = ChildcareService.bulk_create_monthly_transactions(2026, 1, [
        {'child_id': child_one.id, 'account_id': 1},
        {'child_id': child_two.id, 'account_id': 2},
    ])

    assert len(created) == 1
    assert calls == [(2026, 1, child_two.id, 2)]
