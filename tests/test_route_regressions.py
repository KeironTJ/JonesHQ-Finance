from datetime import date
from decimal import Decimal

from extensions import db
from models.pension_snapshots import PensionSnapshot
from models.pensions import Pension
from models.tax_settings import TaxSettings
from services.planning.pension_service import PensionService
from tests.auth_helpers import login_client


def test_combined_snapshots_group_pensions_by_review_date(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: None)
    first = Pension(family_id=family.id, person='A', provider='Alpha', current_value=Decimal('100'))
    second = Pension(family_id=family.id, person='A', provider='Beta', current_value=Decimal('50'))
    db.session.add_all([first, second])
    db.session.flush()
    db.session.add_all([
        PensionSnapshot(family_id=family.id, pension_id=first.id, review_date=date(2026, 1, 1), value=Decimal('100')),
        PensionSnapshot(family_id=family.id, pension_id=second.id, review_date=date(2026, 1, 1), value=Decimal('50')),
        PensionSnapshot(family_id=family.id, pension_id=first.id, review_date=date(2026, 2, 1), value=Decimal('165')),
    ])
    db.session.commit()

    rows = PensionService.get_combined_snapshots()

    assert [row['review_date'] for row in rows] == [date(2026, 1, 1), date(2026, 2, 1)]
    assert rows[0]['total_value'] == Decimal('150')
    assert set(rows[0]['pensions']) == {'Alpha', 'Beta'}
    assert rows[1]['total_growth_percent'] == Decimal('10')


def test_tax_settings_pages_render_and_save(app, family, user):
    tax_year = TaxSettings(family_id=family.id, tax_year='2026-2027', effective_from=date(2026, 4, 6))
    db.session.add(tax_year)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    listing = client.get('/settings/tax')
    assert listing.status_code == 200
    assert b'2026-2027' in listing.data
    assert b'20%' in listing.data

    edit = client.get(f'/settings/tax/{tax_year.id}/edit')
    assert edit.status_code == 200
    assert b'value="12570.00"' in edit.data

    response = client.post(f'/settings/tax/{tax_year.id}/edit', data={
        'personal_allowance': '12570', 'basic_rate_limit': '50270', 'higher_rate_limit': '125140',
        'basic_rate': '21', 'higher_rate': '40', 'additional_rate': '45',
        'ni_threshold': '12570', 'ni_upper_earnings': '50270',
        'ni_basic_rate': '8', 'ni_additional_rate': '2', 'is_active': 'on',
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(TaxSettings, tax_year.id).basic_rate == Decimal('0.21')
