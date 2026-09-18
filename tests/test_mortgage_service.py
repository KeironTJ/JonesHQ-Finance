from datetime import date
from decimal import Decimal

from extensions import db
from models.property import Property
from models.mortgage import MortgageProduct
from models.property_valuation_snapshot import PropertyValuationSnapshot
from services.mortgage_service import MortgageService


def test_create_property_assigns_family_and_converts_values(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    property_obj = MortgageService.create_property({
        'address': '1 Test Street',
        'purchase_date': '2020-05-10',
        'purchase_price': '250000',
        'current_valuation': '300000',
        'annual_appreciation_rate': '3.5',
        'is_primary_residence': 'on',
    })

    assert property_obj.family_id == family.id
    assert property_obj.purchase_date == date(2020, 5, 10)
    assert property_obj.purchase_price == Decimal('250000')
    assert property_obj.current_valuation == Decimal('300000')
    assert property_obj.annual_appreciation_rate == Decimal('3.5')
    assert property_obj.is_primary_residence is True
    assert db.session.get(Property, property_obj.id) is property_obj


def test_create_and_update_product_assign_family_and_financial_values(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    property_obj = MortgageService.create_property({'address': '1 Test Street'})
    product_data = {
        'lender': 'Test Bank',
        'product_name': 'Fixed',
        'start_date': '2026-01-01',
        'end_date': '2028-01-01',
        'term_months': '24',
        'initial_balance': '200000',
        'current_balance': '195000',
        'annual_rate': '4.5',
        'monthly_payment': '1100',
        'payment_day': '15',
        'account_id': '',
        'vendor_id': '',
        'category_id': '',
        'is_active': 'on',
        'is_current': 'on',
        'ltv_ratio': '65.0',
    }

    product = MortgageService.create_product(property_obj.id, product_data)
    product_data['monthly_payment'] = '1200'
    updated = MortgageService.update_product(product.id, product_data)

    assert product.family_id == family.id
    assert product.property_id == property_obj.id
    assert updated.monthly_payment == Decimal('1200')
    assert updated.annual_rate == Decimal('4.5')
    assert db.session.get(MortgageProduct, product.id) is updated


def test_add_valuation_calculates_change_and_updates_property(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    property_obj = MortgageService.create_property({
        'address': '1 Test Street',
        'current_valuation': '300000',
    })

    first, first_change = MortgageService.add_valuation(property_obj.id, {
        'valuation_date': '2025-01-01',
        'value': '300000',
        'source': 'manual',
        'notes': '',
    })
    second, second_change = MortgageService.add_valuation(property_obj.id, {
        'valuation_date': '2026-01-01',
        'value': '330000',
        'source': 'estate_agent',
        'notes': 'Annual review',
    })

    assert first.family_id == family.id
    assert first_change is None
    assert second.change_percent == Decimal('10')
    assert second_change == Decimal('10')
    assert property_obj.current_valuation == Decimal('330000')
    assert PropertyValuationSnapshot.query.count() == 2


def test_delete_product_and_property_are_service_owned(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    property_obj = MortgageService.create_property({'address': 'Delete Street'})
    product = MortgageService.create_product(property_obj.id, {
        'lender': 'Delete Bank', 'product_name': 'Fixed',
        'start_date': '2026-01-01', 'end_date': '2028-01-01',
        'term_months': '24', 'initial_balance': '100000',
        'current_balance': '95000', 'annual_rate': '4',
        'monthly_payment': '600', 'payment_day': '1',
        'account_id': '', 'vendor_id': '', 'category_id': '',
        'is_active': 'on', 'is_current': 'on', 'ltv_ratio': '',
    })

    property_id, label = MortgageService.delete_product(product.id)
    address = MortgageService.delete_property(property_id)

    assert label == 'Delete Bank - Fixed'
    assert address == 'Delete Street'
    assert db.session.get(Property, property_id) is None


def test_update_property_converts_form_values(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    property_obj = MortgageService.create_property({'address': 'Old Address'})

    updated = MortgageService.update_property(property_obj.id, {
        'address': 'New Address',
        'purchase_date': '2020-01-02',
        'purchase_price': '200000',
        'current_valuation': '250000',
        'annual_appreciation_rate': '3.5',
        'is_primary_residence': 'on',
        'is_active': 'on',
    })

    assert updated.address == 'New Address'
    assert updated.purchase_price == Decimal('200000')
    assert updated.current_valuation == Decimal('250000')
