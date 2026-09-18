from datetime import date
from decimal import Decimal

from extensions import db
from models.pensions import Pension
from models.pension_snapshots import PensionSnapshot
from services.pension_service import PensionService


def test_add_actual_snapshot_calculates_growth_and_updates_pension(
    app, family, monkeypatch
):
    monkeypatch.setattr('services.pension_service.get_family_id', lambda: family.id)
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
    assert PensionSnapshot.query.count() == 2


def test_create_pension_assigns_family_and_converts_values(app, family, monkeypatch):
    monkeypatch.setattr('services.pension_service.get_family_id', lambda: family.id)
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
