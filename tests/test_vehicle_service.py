from decimal import Decimal

from extensions import db
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from services.vehicles.vehicle_service import VehicleService
from werkzeug.datastructures import MultiDict


def test_vehicle_crud_assigns_family_and_normalizes_values(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    vehicle = VehicleService.create_vehicle({
        'name': 'Family Car',
        'make': 'Test',
        'model': 'Runner',
        'registration': 'ab12 cde',
        'tank_size': '12.5',
        'fuel_type': 'Petrol',
        'year': '2024',
        'starting_mileage': '1000',
        'fuel_account_id': '',
        'refuel_threshold_pct': '90',
    })
    assert vehicle.family_id == family.id
    assert vehicle.registration == 'AB12 CDE'
    assert vehicle.tank_size == Decimal('12.5')

    updated = VehicleService.update_vehicle(vehicle.id, {
        'name': 'Updated Car',
        'make': 'Test',
        'model': 'Runner Plus',
        'registration': 'xy99 zzz',
        'tank_size': '13.0',
        'fuel_type': 'Diesel',
        'year': '2025',
        'fuel_account_id': '',
        'refuel_threshold_pct': '95',
        'is_active': 'on',
    })
    deleted_name = VehicleService.delete_vehicle(vehicle.id)

    assert updated.name == 'Updated Car'
    assert updated.registration == 'XY99 ZZZ'
    assert updated.fuel_type == 'Diesel'
    assert deleted_name == 'Updated Car'
    assert db.session.get(Vehicle, vehicle.id) is None


def test_fuel_crud_assigns_family_and_recalculates_metrics(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Fuel Car', 'make': 'Test', 'model': 'Fuel',
        'registration': 'FU12 ELL', 'tank_size': '12', 'fuel_type': 'Petrol',
    })

    record = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id),
        'date': '2026-01-01',
        'price_per_litre': '150',
        'mileage': '1000',
        'cost': '30',
        'gallons': '5',
        'is_partial_fill': '0',
    })
    updated = VehicleService.update_fuel_record(record.id, {
        'date': '2026-01-02',
        'price_per_litre': '155',
        'mileage': '1100',
        'cost': '35',
        'gallons': '5.5',
        'is_partial_fill': '1',
    })
    deleted_vehicle_id = VehicleService.delete_fuel_record(record.id)

    assert record.family_id == family.id
    assert record.actual_miles == 0
    assert updated.cost == Decimal('35')
    assert updated.is_partial_fill is True
    assert deleted_vehicle_id == vehicle.id
    assert db.session.get(FuelRecord, record.id) is None


def test_trip_crud_assigns_family_and_tracks_cumulative_miles(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Trip Car', 'make': 'Test', 'model': 'Trip',
        'registration': 'TR12 IPS', 'tank_size': '12', 'fuel_type': 'Petrol',
    })

    first = VehicleService.create_trip({
        'vehicle_id': str(vehicle.id),
        'date': '2026-01-01',
        'trip_type': 'business',
        'miles': '20',
        'journey_description': 'Client visit',
        'school_holidays': '',
    })
    updated = VehicleService.update_trip(first.id, {
        'date': '2026-01-02',
        'trip_type': 'personal',
        'miles': '25',
        'journey_description': 'Personal trip',
        'school_holidays': '',
    })
    deleted_vehicle_id = VehicleService.delete_trip(first.id)

    assert first.family_id == family.id
    assert first.cumulative_total_miles == 20
    assert updated.total_miles == 25
    assert updated.personal_miles == 25
    assert updated.business_miles == 0
    assert deleted_vehicle_id == vehicle.id
    assert db.session.get(Trip, first.id) is None


def test_bulk_create_trips_expands_selected_weekdays(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Bulk Car', 'make': 'Test', 'model': 'Bulk',
        'registration': 'BU12 LKS', 'tank_size': '12', 'fuel_type': 'Petrol',
    })

    created = VehicleService.bulk_create_trips(MultiDict([
        ('vehicle_id', str(vehicle.id)),
        ('start_date', '2026-01-05'),
        ('end_date', '2026-01-09'),
        ('days', '0'),
        ('days', '2'),
        ('trip_type', 'business'),
        ('miles', '20'),
        ('journey_description', 'Regular route'),
    ]))

    assert len(created) == 2
    assert [trip.date.isoformat() for trip in created] == ['2026-01-05', '2026-01-07']
    assert all(trip.family_id == family.id for trip in created)
    assert all(trip.business_miles == 20 for trip in created)
