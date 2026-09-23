from sqlalchemy import UniqueConstraint

from extensions import db
from models.family import Family
from models.vendors import Vendor, VendorType
from services.finance.vendor_service import DEFAULT_VENDOR_TYPES, VendorService


def test_vendor_type_and_vendor_creation_assign_family(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    vendor_type = VendorService.create_type('Grocery', 1, True)
    vendor = VendorService.create_vendor('Market', str(vendor_type.id), None, '', '')

    assert vendor_type.family_id == family.id
    assert vendor.family_id == family.id
    assert vendor.name == 'Market'
    assert vendor.vendor_type_id == vendor_type.id


def test_vendor_type_duplicate_and_seed_behaviour(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    first = VendorType(family_id=family.id, name='Fuel', is_active=True, sort_order=1)
    db.session.add(first)
    db.session.commit()

    assert VendorService.find_type('fuel') is first
    assert VendorService.seed_types() is True
    assert VendorService.seed_types() is False


def test_vendor_type_names_are_unique_per_family():
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in VendorType.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ('family_id', 'name') in unique_columns
    assert ('name',) not in unique_columns


def test_seed_types_completes_partial_family_setup(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    db.session.add(VendorType(
        family_id=family.id,
        name='Fuel',
        is_active=True,
        sort_order=99,
    ))
    db.session.commit()

    assert VendorService.seed_types() is True
    assert {vendor_type.name for vendor_type in VendorService.list_types()} == set(
        DEFAULT_VENDOR_TYPES
    )


def test_seed_types_allows_same_defaults_for_another_family(
    app, family, monkeypatch
):
    current_family_id = {'value': family.id}
    monkeypatch.setattr(
        'utils.db_helpers.get_family_id', lambda: current_family_id['value']
    )
    assert VendorService.seed_types() is True

    other_family = Family(name='Second Family')
    db.session.add(other_family)
    db.session.commit()
    current_family_id['value'] = other_family.id

    assert VendorService.seed_types() is True
    assert len(VendorService.list_types()) == len(DEFAULT_VENDOR_TYPES)


def test_delete_unused_vendor_and_preserve_used_vendor(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    unused = Vendor(family_id=family.id, name='Unused')
    db.session.add(unused)
    db.session.commit()

    result = VendorService.delete_vendor(unused.id)

    assert result == {'deleted': True, 'name': 'Unused'}
    assert db.session.get(Vendor, unused.id) is None
