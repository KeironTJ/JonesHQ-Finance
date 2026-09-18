from datetime import date
from decimal import Decimal

from extensions import db
from models.tax_settings import TaxSettings
from models.settings import Settings
from services.platform.settings_service import SettingsService


def test_update_tax_settings_converts_percentages_and_preserves_family(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    tax_year = TaxSettings(
        family_id=family.id,
        tax_year='2026-2027',
        effective_from=date(2026, 4, 6),
    )
    db.session.add(tax_year)
    db.session.commit()

    updated = SettingsService.update_tax_settings(tax_year.id, {
        'personal_allowance': '13000',
        'basic_rate_limit': '51000',
        'higher_rate_limit': '126000',
        'basic_rate': '20',
        'higher_rate': '40',
        'additional_rate': '45',
        'ni_threshold': '13000',
        'ni_upper_earnings': '51000',
        'ni_basic_rate': '8',
        'ni_additional_rate': '2',
        'notes': 'Updated rates',
        'is_active': 'on',
    })

    assert updated.family_id == family.id
    assert updated.personal_allowance == Decimal('13000')
    assert updated.basic_rate == Decimal('0.20')
    assert updated.ni_basic_rate == Decimal('0.08')
    assert updated.notes == 'Updated rates'
    assert updated.is_active is True


def test_clear_networth_start_date_removes_setting(app):
    setting = Settings(
        key='networth.start_date',
        value='2020-01-01',
        setting_type='date',
    )
    db.session.add(setting)
    db.session.commit()

    removed = SettingsService.clear_networth_start_date()
    db.session.commit()

    assert removed.id == setting.id
    assert db.session.get(Settings, setting.id) is None
