from datetime import date
from decimal import Decimal

from extensions import db
from models.childcare import Child, ChildActivityType
from models.accounts import Account
from models.transactions import Transaction
from models.childcare import MonthlyChildcareSummary
from models.categories import Category
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


def test_update_monthly_transaction_and_set_default_account(app, family, monkeypatch):
    monkeypatch.setattr('services.childcare_service.get_family_id', lambda: family.id)
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
    monkeypatch.setattr('services.childcare_service.get_family_id', lambda: family.id)
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
        'services.childcare_service.ChildcareService.create_monthly_transaction',
        staticmethod(fake_create),
    )
    created = ChildcareService.bulk_create_monthly_transactions(2026, 1, [
        {'child_id': child_one.id, 'account_id': 1},
        {'child_id': child_two.id, 'account_id': 2},
    ])

    assert len(created) == 1
    assert calls == [(2026, 1, child_two.id, 2)]
