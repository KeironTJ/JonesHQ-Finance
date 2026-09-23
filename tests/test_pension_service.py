from datetime import date
from decimal import Decimal

from extensions import db
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from services.planning.pension_service import PensionService


def test_add_actual_snapshot_calculates_growth_and_updates_pension(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    pension = Pension(
        family_id=family.id,
        person='Household',
        provider='Test Provider',
        current_value=Decimal('10000'),
        contribution_rate=Decimal('5'),
        employer_contribution=Decimal('3'),
        retirement_age=65,
        monthly_contribution=Decimal('100'),
        is_active=True,
    )
    db.session.add(pension)
    db.session.commit()

    first, first_growth, _ = PensionService.add_actual_snapshot(
        pension.id, date(2025, 1, 1), Decimal('10000')
    )
    second, second_growth, updated_pension = PensionService.add_actual_snapshot(
        pension.id, date(2026, 1, 1), Decimal('11000')
    )

    assert first.family_id == family.id
    assert first_growth is None
    assert second.growth_percent == Decimal('10')
    assert second_growth == Decimal('10')
    assert updated_pension.current_value == Decimal('11000')


def test_private_pension_and_snapshots_hidden_from_other_family_members(
    app, family, monkeypatch, user
):
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    pension = PensionService.create_pension({
        'person': 'Household',
        'provider': 'Test Provider',
        'current_value': '10000',
        'visibility': 'private',
    })

    assert pension.owner_id == user.id
    assert pension.is_private is True

    snapshot, _, _ = PensionService.add_actual_snapshot(
        pension.id, date(2026, 1, 1), Decimal('10000')
    )

    assert pension in family_query(Pension).all()
    assert snapshot in family_query(PensionSnapshot).all()

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)
    assert pension not in family_query(Pension).all()
    assert snapshot not in family_query(PensionSnapshot).all()


def test_create_pension_assigns_family_and_converts_values(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    pension = PensionService.create_pension({
        'person': 'Household',
        'provider': 'Test Provider',
        'account_number': '123',
        'current_value': '5000',
        'contribution_rate': '5',
        'employer_contribution': '3',
        'is_active': 'on',
        'retirement_age': '65',
        'monthly_contribution': '100',
    })

    assert pension.family_id == family.id
    assert pension.current_value == Decimal('5000')
    assert pension.monthly_contribution == Decimal('100')


def test_update_and_delete_pension(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    pension = PensionService.create_pension({
        'person': 'Household',
        'provider': 'Old Provider',
        'current_value': '5000',
        'contribution_rate': '2',
        'employer_contribution': '2',
        'is_active': 'on',
        'retirement_age': '65',
        'monthly_contribution': '100',
    })

    updated = PensionService.update_pension(pension.id, {
        'person': 'Household',
        'provider': 'New Provider',
        'account_number': 'ABC',
        'current_value': '6000',
        'contribution_rate': '5',
        'employer_contribution': '3',
        'is_active': 'on',
        'retirement_age': '67',
        'monthly_contribution': '150',
    })
    PensionService.delete_pension(pension.id)

    assert updated.provider == 'New Provider'
    assert updated.current_value == Decimal('6000')
    assert updated.retirement_age == 67
    assert db.session.get(Pension, pension.id) is None


def test_delete_pension_snapshot_is_service_owned(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    pension = PensionService.create_pension({
        'person': 'Household', 'provider': 'Snapshot Provider',
        'current_value': '1000', 'contribution_rate': '0',
        'employer_contribution': '0', 'is_active': 'on',
        'retirement_age': '65', 'monthly_contribution': '0',
    })
    snapshot = PensionSnapshot(
        family_id=family.id, pension_id=pension.id,
        review_date=date(2026, 1, 1), value=Decimal('1000'),
    )
    db.session.add(snapshot)
    db.session.commit()

    PensionService.delete_snapshot(snapshot.id)

    assert db.session.get(PensionSnapshot, snapshot.id) is None


def test_confirm_snapshot_updates_actual_value_and_growth(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    pension = PensionService.create_pension({
        'person': 'Household', 'provider': 'Confirm Provider',
        'current_value': '1000', 'contribution_rate': '0',
        'employer_contribution': '0', 'is_active': 'on',
        'retirement_age': '65', 'monthly_contribution': '0',
    })
    previous = PensionSnapshot(
        family_id=family.id, pension_id=pension.id,
        review_date=date(2025, 1, 1), value=Decimal('1000'),
    )
    projected = PensionSnapshot(
        family_id=family.id, pension_id=pension.id,
        review_date=date(2026, 1, 1), value=Decimal('1100'),
        is_projection=True, scenario_name='default',
    )
    db.session.add_all([previous, projected])
    db.session.commit()

    updated_pension = PensionService.confirm_snapshot(
        pension.id, projected.id, Decimal('1200')
    )

    assert updated_pension.current_value == Decimal('1200')
    assert projected.is_projection is False
    assert projected.growth_percent == Decimal('20')
