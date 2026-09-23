from datetime import date
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.family import Family
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


def test_update_default_account_for_current_user(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.platform.settings_service.get_current_user_id', lambda: user.id
    )
    account = Account(
        family_id=family.id,
        name='Personal Current',
        account_type='Personal',
        is_active=True,
    )
    db.session.add(account)
    db.session.flush()

    selected = SettingsService.update_default_account({
        'default_account_id': str(account.id),
    })
    db.session.commit()

    assert selected == account
    assert user.default_account_id == account.id


def test_update_default_account_rejects_other_family(app, family, user, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.platform.settings_service.get_current_user_id', lambda: user.id
    )
    other_family = Family(name='Other Family')
    db.session.add(other_family)
    db.session.flush()
    other_account = Account(
        family_id=other_family.id,
        name='Other Current',
        account_type='Current',
        is_active=True,
    )
    db.session.add(other_account)
    db.session.flush()

    with pytest.raises(ValueError, match='active account you can access'):
        SettingsService.update_default_account({
            'default_account_id': str(other_account.id),
        })

    assert user.default_account_id is None
