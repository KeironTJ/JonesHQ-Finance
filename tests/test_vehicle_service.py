from decimal import Decimal
from datetime import date, timedelta

import pytest
from extensions import db
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.trip_schedule import TripSchedule
from models.trip_template import TripTemplate
from models.accounts import Account
from models.family import Family
from services.vehicles.vehicle_service import VehicleService
from services.vehicles.trip_schedule_service import TripScheduleService
from services.vehicles.fuel_forecasting_service import FuelForecastingService
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound


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


def test_vehicle_rejects_fuel_account_from_another_family_on_create(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    other_family = Family(name='Other Family')
    db.session.add(other_family)
    db.session.flush()
    account = Account(
        family_id=other_family.id, name='Other account',
        account_type='Current', balance=0, is_active=True,
    )
    db.session.add(account)
    db.session.commit()

    with pytest.raises(ValueError, match='Invalid fuel account selected'):
        VehicleService.create_vehicle({
            'name': 'Family Car',
            'registration': 'AB12 CDE',
            'fuel_account_id': str(account.id),
        })

    assert Vehicle.query.filter_by(family_id=family.id).count() == 0


def test_vehicle_rejects_fuel_account_from_another_family_on_update(
    app, family, monkeypatch
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Family Car',
        'make': 'Test',
        'model': 'Runner',
        'registration': 'AB12 CDE',
        'fuel_account_id': '',
    })
    other_family = Family(name='Other Family')
    db.session.add(other_family)
    db.session.flush()
    account = Account(
        family_id=other_family.id, name='Other account',
        account_type='Current', balance=0, is_active=True,
    )
    db.session.add(account)
    db.session.commit()

    with pytest.raises(ValueError, match='Invalid fuel account selected'):
        VehicleService.update_vehicle(vehicle.id, {
            'name': 'Changed Car',
            'fuel_account_id': str(account.id),
        })

    assert vehicle.name == 'Family Car'
    assert vehicle.fuel_account_id is None


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
    second = VehicleService.create_trip({
        'vehicle_id': str(vehicle.id),
        'date': '2026-01-03',
        'trip_type': 'personal',
        'miles': '10',
        'journey_description': 'Errand',
        'school_holidays': '',
    })
    updated = VehicleService.update_trip(first.id, {
        'date': '2026-01-02',
        'trip_type': 'personal',
        'miles': '25',
        'journey_description': 'Personal trip',
        'school_holidays': '',
    })
    assert first.family_id == family.id
    assert first.cumulative_total_miles == 25
    assert updated.total_miles == 25
    assert updated.personal_miles == 25
    assert updated.business_miles == 0
    assert second.cumulative_total_miles == 35
    deleted_vehicle_id = VehicleService.delete_trip(first.id)
    assert deleted_vehicle_id == vehicle.id
    assert db.session.get(Trip, first.id) is None
    assert second.cumulative_total_miles == 10


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
        ('school_holidays', 'Christmas'),
    ]))

    assert len(created) == 2
    assert [trip.date.isoformat() for trip in created] == ['2026-01-05', '2026-01-07']
    assert all(trip.family_id == family.id for trip in created)
    assert all(trip.business_miles == 20 for trip in created)
    assert all(trip.school_holidays == 'Christmas' for trip in created)


def test_bulk_create_trips_rejects_ranges_over_one_year(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Long Range Car', 'make': 'Test', 'model': 'Bulk',
        'registration': 'LR12 CAR', 'fuel_type': 'Petrol',
    })

    with pytest.raises(ValueError, match='366 days'):
        VehicleService.bulk_create_trips(MultiDict([
            ('vehicle_id', str(vehicle.id)),
            ('start_date', '2026-01-01'),
            ('end_date', '2027-01-02'),
            ('days', '0'),
            ('trip_type', 'personal'),
            ('miles', '20'),
        ]))


def test_trip_template_crud_preserves_family_and_vehicle(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Saved Journey Car', 'make': 'Test', 'model': 'Saved',
        'registration': 'SJ12 CAR', 'fuel_type': 'Petrol',
    })

    template = VehicleService.create_trip_template({
        'vehicle_id': str(vehicle.id),
        'name': 'Work commute',
        'trip_type': 'business',
        'miles': '24',
        'journey_description': 'Office',
    })
    updated = VehicleService.update_trip_template(template.id, {
        'vehicle_id': str(vehicle.id),
        'name': 'Updated commute',
        'trip_type': 'personal',
        'miles': '18',
        'journey_description': 'Office and errands',
    })

    assert template.family_id == family.id
    assert template.vehicle_id == vehicle.id
    assert updated.name == 'Updated commute'
    assert updated.trip_type == 'personal'
    assert updated.miles == 18
    assert updated.journey_description == 'Office and errands'

    VehicleService.delete_trip_template(template.id)
    assert db.session.get(TripTemplate, template.id) is None


def test_trip_template_rejects_vehicle_from_another_family(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    other_family = Family(name='Other Family')
    db.session.add(other_family)
    db.session.flush()
    vehicle = Vehicle(
        family_id=other_family.id,
        name='Other car',
        make='Test',
        model='Other',
        registration='OT12 CAR',
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.commit()

    with pytest.raises(NotFound):
        VehicleService.create_trip_template({
            'vehicle_id': str(vehicle.id),
            'name': 'Cross-family journey',
            'trip_type': 'personal',
            'miles': '5',
        })


def test_trip_schedule_plans_idempotently_and_tracks_exceptions(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Routine Car', 'make': 'Test', 'model': 'Routine',
        'registration': 'RT12 CAR', 'fuel_type': 'Petrol',
    })
    today = date.today()
    weekday = today.weekday()
    schedule, generated_vehicles = TripScheduleService.create_schedule(MultiDict([
        ('vehicle_id', str(vehicle.id)),
        ('name', 'Fortnightly commute'),
        ('trip_type', 'business'),
        ('miles', '22'),
        ('journey_description', 'Office'),
        ('frequency', 'fortnightly'),
        ('start_date', today.isoformat()),
        ('end_date', ''),
        ('days', str(weekday)),
    ]))

    planned = Trip.query.filter_by(schedule_id=schedule.id).order_by(
        Trip.scheduled_date,
    ).all()
    assert generated_vehicles == {vehicle.id}
    assert len(planned) == 7
    assert all(trip.trip_status == 'planned' for trip in planned)
    assert all(trip.business_miles == 22 for trip in planned)
    assert all(
        (planned[index + 1].scheduled_date - planned[index].scheduled_date).days == 14
        for index in range(len(planned) - 1)
    )
    assert TripScheduleService.ensure_upcoming_trips(today=today) == set()

    TripScheduleService.set_occurrence_status(planned[0].id, 'skipped')
    TripScheduleService.set_occurrence_status(planned[1].id, 'actual')
    assert planned[1].cumulative_total_miles == 22
    assert TripScheduleService.ensure_upcoming_trips(today=today) == set()
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 7

    TripScheduleService.set_schedule_active(schedule.id, False)
    assert not schedule.is_active
    assert Trip.query.filter_by(
        schedule_id=schedule.id, trip_status='planned',
    ).count() == 0

    TripScheduleService.set_schedule_active(schedule.id, True)
    assert schedule.is_active
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 7

    replacement_vehicle = VehicleService.create_vehicle({
        'name': 'Replacement Routine Car', 'make': 'Test', 'model': 'Routine',
        'registration': 'RT13 CAR', 'fuel_type': 'Petrol',
    })
    schedule, affected_vehicle_ids = TripScheduleService.update_schedule(
        schedule.id,
        MultiDict([
            ('vehicle_id', str(replacement_vehicle.id)),
            ('name', 'Weekly commute'),
            ('trip_type', 'business'),
            ('miles', '24'),
            ('journey_description', 'Office'),
            ('frequency', 'weekly'),
            ('start_date', today.isoformat()),
            ('end_date', (today + timedelta(days=21)).isoformat()),
            ('days', str(weekday)),
        ]),
    )
    assert affected_vehicle_ids == {vehicle.id, replacement_vehicle.id}
    assert schedule.frequency == 'weekly'
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 4
    skipped = Trip.query.filter_by(
        schedule_id=schedule.id, trip_status='skipped',
    ).one()
    assert skipped.vehicle_id == replacement_vehicle.id
    assert skipped.total_miles == 24

    TripScheduleService.delete_schedule(schedule.id)
    remaining = Trip.query.all()
    assert len(remaining) == 1
    assert remaining[0].trip_status == 'actual'
    assert remaining[0].schedule_id is None


@pytest.mark.parametrize(('start_offset', 'end_offset', 'frequency'), [
    (0, 126, 'weekly'),
    (0, 126, 'fortnightly'),
    (112, 140, 'weekly'),
    (0, 21, 'weekly'),
    (-14, -1, 'weekly'),
    (0, None, 'weekly'),
])
def test_trip_schedule_occurrences_use_end_date(
    app, start_offset, end_offset, frequency,
):
    today = date(2026, 1, 5)
    schedule = TripSchedule(
        start_date=today + timedelta(days=start_offset),
        end_date=today + timedelta(days=end_offset) if end_offset is not None else None,
        weekdays=str(today.weekday()),
        frequency=frequency,
    )
    interval = 14 if frequency == 'fortnightly' else 7
    expected_end = end_offset if end_offset is not None else 89

    assert TripScheduleService._occurrence_dates(schedule, today) == [
        today + timedelta(days=offset)
        for offset in range(max(0, start_offset), expected_end + 1, interval)
    ]


def _routine_vehicle_and_schedule(family, monkeypatch, start, days=7):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = VehicleService.create_vehicle({
        'name': 'Daily Car', 'make': 'Test', 'model': 'Routine',
        'registration': 'DY12 CAR', 'fuel_type': 'Petrol',
    })
    schedule, _ = TripScheduleService.create_schedule(MultiDict([
        ('vehicle_id', str(vehicle.id)),
        ('name', 'Commute'),
        ('trip_type', 'personal'),
        ('miles', '10'),
        ('journey_description', 'Office'),
        ('frequency', 'weekly'),
        ('start_date', start.isoformat()),
        ('end_date', (start + timedelta(days=days - 1)).isoformat()),
        *[('days', str(day)) for day in range(7)],
    ]))
    trips = Trip.query.filter_by(schedule_id=schedule.id).order_by(Trip.date).all()
    return vehicle, schedule, trips


def test_trip_schedule_materializes_full_end_date_across_lifecycle(
    app, family, monkeypatch,
):
    today = date.today()
    vehicle, schedule, trips = _routine_vehicle_and_schedule(
        family, monkeypatch, today, days=127,
    )
    expected_dates = [today + timedelta(days=offset) for offset in range(127)]
    assert [trip.scheduled_date for trip in trips] == expected_dates
    assert TripScheduleService.ensure_upcoming_trips(today=today) == set()

    # Simulate an existing routine generated under the old 90-day limit.
    for trip in trips[90:]:
        db.session.delete(trip)
    db.session.commit()
    assert TripScheduleService.ensure_upcoming_trips(today=today) == {vehicle.id}
    _, occurrences = TripScheduleService.get_occurrences(schedule.id, today=today)
    assert [trip.scheduled_date for trip in occurrences] == expected_dates

    TripScheduleService.set_schedule_active(schedule.id, False)
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 0
    TripScheduleService.set_schedule_active(schedule.id, True)
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 127

    for days in (155, 15):
        TripScheduleService.update_schedule(schedule.id, MultiDict([
            ('vehicle_id', str(vehicle.id)),
            ('name', schedule.name),
            ('trip_type', schedule.trip_type),
            ('miles', str(schedule.miles)),
            ('frequency', schedule.frequency),
            ('start_date', today.isoformat()),
            ('end_date', (today + timedelta(days=days - 1)).isoformat()),
            *[('days', str(day)) for day in range(7)],
        ]))
        planned = Trip.query.filter_by(schedule_id=schedule.id).order_by(
            Trip.scheduled_date,
        ).all()
        assert [trip.scheduled_date for trip in planned] == [
            today + timedelta(days=offset) for offset in range(days)
        ]
        assert TripScheduleService.ensure_upcoming_trips(today=today) == set()


def test_fuel_record_confirms_planned_trips_up_to_fill_date(app, family, monkeypatch):
    start = date.today() - timedelta(days=3)
    vehicle, _, trips = _routine_vehicle_and_schedule(family, monkeypatch, start)
    other = VehicleService.create_vehicle({
        'name': 'Other Car', 'make': 'Test', 'model': 'Other',
        'registration': 'OT34 CAR', 'fuel_type': 'Petrol',
    })
    other_trip = Trip(
        family_id=family.id, vehicle_id=other.id, date=start,
        total_miles=5, personal_miles=5, trip_status='planned',
    )
    db.session.add(other_trip)
    db.session.commit()
    TripScheduleService.ensure_upcoming_trips(today=start)
    trips = Trip.query.filter_by(vehicle_id=vehicle.id).order_by(Trip.date).all()
    assert len(trips) == 7
    assert all(trip.trip_status == 'planned' for trip in trips)

    fill = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id), 'date': (start + timedelta(days=1)).isoformat(),
        'price_per_litre': '150', 'mileage': '1000', 'cost': '30', 'gallons': '10',
    })

    assert fill.confirmed_trip_count == 2
    assert [trip.trip_status for trip in trips[:3]] == ['actual', 'actual', 'planned']
    assert trips[1].cumulative_total_miles == 20
    assert other_trip.trip_status == 'planned'

    count, vehicle_ids = VehicleService.confirm_due_trips(vehicle.id)
    assert count == 2
    assert vehicle_ids == {vehicle.id}
    assert [trip.trip_status for trip in trips[:5]] == ['actual'] * 4 + ['planned']
    assert other_trip.trip_status == 'planned'


def test_editing_one_occurrence_survives_routine_changes_until_reset(
    app, family, monkeypatch,
):
    start = date.today() + timedelta(days=1)
    vehicle, schedule, trips = _routine_vehicle_and_schedule(family, monkeypatch, start)
    other = VehicleService.create_vehicle({
        'name': 'Borrowed Car', 'make': 'Test', 'model': 'Other',
        'registration': 'BR12 CAR', 'fuel_type': 'Petrol',
    })
    edited = trips[2]

    updated = VehicleService.update_trip(edited.id, {
        'vehicle_id': str(other.id),
        'date': edited.date.isoformat(),
        'trip_type': 'personal',
        'miles': '35',
        'journey_description': 'Detour via shops',
        'school_holidays': '',
    })
    assert updated.trip_status == 'planned'
    assert updated.is_modified is True
    assert updated.vehicle_id == other.id
    assert updated.previous_vehicle_id == vehicle.id

    TripScheduleService.update_schedule(schedule.id, MultiDict([
        ('vehicle_id', str(vehicle.id)),
        ('name', 'Commute'),
        ('trip_type', 'personal'),
        ('miles', '12'),
        ('journey_description', 'New office'),
        ('frequency', 'weekly'),
        ('start_date', start.isoformat()),
        ('end_date', (start + timedelta(days=6)).isoformat()),
        *[('days', str(day)) for day in range(7)],
    ]))
    edited = db.session.get(Trip, edited.id)
    assert edited.total_miles == 35
    assert edited.journey_description == 'Detour via shops'
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 7
    assert Trip.query.filter_by(schedule_id=schedule.id, total_miles=12).count() == 6

    overview = {item['schedule'].id: item for item in TripScheduleService.get_overview()}
    assert overview[schedule.id]['modified_count'] == 1
    assert overview[schedule.id]['upcoming_count'] == 7

    assert TripScheduleService.reset_occurrence(edited.id) == {other.id, vehicle.id}
    assert edited.is_modified is False
    assert edited.vehicle_id == vehicle.id
    assert edited.total_miles == 12
    assert edited.journey_description == 'New office'
    assert edited.trip_status == 'planned'

    _, occurrences = TripScheduleService.get_occurrences(schedule.id)
    assert [trip.scheduled_date for trip in occurrences] == [
        start + timedelta(days=offset) for offset in range(7)
    ]


def _manual_trip(vehicle, day, miles=5):
    trip = Trip(
        family_id=vehicle.family_id, vehicle_id=vehicle.id, date=day,
        total_miles=miles, personal_miles=miles,
    )
    db.session.add(trip)
    db.session.commit()
    return trip


@pytest.mark.parametrize('mode', ['keep', 'skip', 'end'])
def test_clear_future_trips_modes(app, family, monkeypatch, mode):
    today = date.today()
    start = today + timedelta(days=1)
    vehicle, schedule, _ = _routine_vehicle_and_schedule(family, monkeypatch, start, days=10)
    other = VehicleService.create_vehicle({
        'name': 'Untouched Car', 'make': 'Test', 'model': 'Other',
        'registration': 'UT12 CAR', 'fuel_type': 'Petrol',
    })
    cutoff = today + timedelta(days=5)
    before = _manual_trip(vehicle, today + timedelta(days=2))
    after = _manual_trip(vehicle, today + timedelta(days=6))
    other_after = _manual_trip(other, today + timedelta(days=6))
    after_id = after.id

    summary, vehicle_ids = TripScheduleService.clear_future_trips(
        cutoff, vehicle_id=vehicle.id, routine_mode=mode,
    )

    assert vehicle_ids == {vehicle.id}
    assert db.session.get(Trip, after_id) is None
    assert db.session.get(Trip, before.id) is not None
    assert db.session.get(Trip, other_after.id) is not None
    routine_before = Trip.query.filter(
        Trip.schedule_id == schedule.id, Trip.date < cutoff,
    ).all()
    assert len(routine_before) == 4
    assert all(trip.trip_status == 'planned' for trip in routine_before)
    routine_after = Trip.query.filter(
        Trip.schedule_id == schedule.id, Trip.date >= cutoff,
    ).all()
    if mode == 'keep':
        assert summary == {'deleted': 1, 'skipped': 0, 'routines_ended': 0}
        assert {trip.trip_status for trip in routine_after} == {'planned'}
        assert len(routine_after) == 6
    elif mode == 'skip':
        assert summary == {'deleted': 1, 'skipped': 6, 'routines_ended': 0}
        assert {trip.trip_status for trip in routine_after} == {'skipped'}
        assert schedule.is_active
    else:
        assert summary == {'deleted': 7, 'skipped': 0, 'routines_ended': 1}
        assert routine_after == []
        assert schedule.end_date == cutoff - timedelta(days=1)
        assert TripScheduleService.ensure_upcoming_trips() == set()
        assert Trip.query.filter_by(schedule_id=schedule.id).count() == 4


def test_clear_future_trips_rejects_past_dates_and_pauses_unstarted_routines(
    app, family, monkeypatch,
):
    today = date.today()
    _, schedule, _ = _routine_vehicle_and_schedule(
        family, monkeypatch, today + timedelta(days=10), days=3,
    )
    with pytest.raises(ValueError, match='after today'):
        TripScheduleService.clear_future_trips(today)
    with pytest.raises(ValueError, match='routine trips'):
        TripScheduleService.clear_future_trips(today + timedelta(days=1), routine_mode='nuke')

    summary, _ = TripScheduleService.clear_future_trips(
        today + timedelta(days=2), routine_mode='end',
    )

    assert summary['routines_ended'] == 1
    assert schedule.is_active is False
    assert Trip.query.filter_by(schedule_id=schedule.id).count() == 0


def test_fortnightly_trip_schedule_uses_calendar_weeks(app):
    schedule = TripSchedule(
        start_date=date(2026, 1, 7),
        end_date=date(2026, 2, 6),
        weekdays='0,4',
        frequency='fortnightly',
    )

    occurrences = TripScheduleService._occurrence_dates(schedule, date(2026, 1, 7))

    assert occurrences == [
        date(2026, 1, 9),
        date(2026, 1, 19),
        date(2026, 1, 23),
        date(2026, 2, 2),
        date(2026, 2, 6),
    ]


def test_forecasts_historical_refills_only_since_latest_fill(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = Vehicle(
        family_id=family.id,
        name='Forecast Car',
        make='Test',
        model='Forecast',
        registration='FC12 AST',
        tank_size=10,
        fuel_type='Petrol',
        refuel_threshold_pct=95,
    )
    db.session.add(vehicle)
    db.session.flush()

    db.session.add_all([
        FuelRecord(
            family_id=family.id, vehicle_id=vehicle.id, date=date(2026, 6, 1),
            price_per_litre=150, mileage=1000, cost=30, gallons=10,
            is_partial_fill=False,
        ),
        FuelRecord(
            family_id=family.id, vehicle_id=vehicle.id, date=date(2026, 9, 1),
            price_per_litre=150, mileage=1110, cost=3, gallons=1,
            is_partial_fill=True,
        ),
        Trip(
            family_id=family.id, vehicle_id=vehicle.id, date=date(2026, 6, 2),
            total_miles=100, personal_miles=100,
        ),
        Trip(
            family_id=family.id, vehicle_id=vehicle.id, date=date(2026, 9, 2),
            total_miles=10, personal_miles=10,
        ),
    ])
    db.session.commit()

    monkeypatch.setattr(FuelForecastingService, 'get_average_mpg', staticmethod(lambda vehicle_id: 10.0))
    monkeypatch.setattr(FuelForecastingService, 'get_average_fuel_price', staticmethod(lambda vehicle_id: 150.0))

    predictions = FuelForecastingService.predict_refills(vehicle.id)

    assert [prediction['trigger_trip_date'].isoformat() for prediction in predictions] == ['2026-09-02']


def test_private_vehicle_and_records_hidden_but_shared_fuel_txn_stays_visible(
    app, family, monkeypatch, user
):
    """Private hides the vehicle and its fuel/trip logs, but a fuel purchase
    transaction posted to a shared account still appears there for everyone."""
    from models.accounts import Account
    from models.transactions import Transaction
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    account = Account(
        family_id=family.id, name='Joint', account_type='Joint',
        balance=0, is_active=True,
    )
    db.session.add(account)
    db.session.flush()

    vehicle = VehicleService.create_vehicle({
        'name': 'Private Car', 'make': 'Test', 'model': 'Private',
        'registration': 'PR1V ATE', 'tank_size': '12', 'fuel_type': 'Petrol',
        'fuel_account_id': str(account.id),
        'visibility': 'private',
    })

    assert vehicle.owner_id == user.id
    assert vehicle.is_private is True
    assert account.owner_id is None  # the account itself stays shared

    fuel_record = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id),
        'date': '2026-01-01',
        'price_per_litre': '150',
        'mileage': '1000',
        'cost': '30',
        'gallons': '5',
        'is_partial_fill': '0',
    })
    bank_transaction = VehicleService.create_fuel_transaction(fuel_record, account.id)

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)

    # Vehicle and its fuel log are hidden from other family members...
    assert vehicle not in family_query(Vehicle).all()
    assert fuel_record not in family_query(FuelRecord).all()
    # ...but the fuel purchase transaction remains visible in the shared account.
    assert bank_transaction in family_query(Transaction).all()


def test_trip_log_periods_only_include_periods_with_entries(app, family, monkeypatch):
    from services.finance.payday_service import PaydayService

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = Vehicle(family_id=family.id, name='Period A', make='T', model='T', registration='PA1', is_active=True)
    other = Vehicle(family_id=family.id, name='Period B', make='T', model='T', registration='PB1', is_active=True)
    db.session.add_all([vehicle, other])
    db.session.flush()

    def add_trip(vehicle_id, day, status='actual'):
        db.session.add(Trip(
            family_id=family.id, vehicle_id=vehicle_id, date=day,
            total_miles=5, personal_miles=5, trip_status=status,
        ))

    jan = date(2024, 1, 20)
    apr = date(2024, 4, 20)
    jul = date(2024, 7, 20)
    add_trip(vehicle.id, jan)
    add_trip(vehicle.id, apr, status='skipped')
    add_trip(other.id, jul)
    db.session.commit()
    jan_label = PaydayService.get_period_for_date(jan)
    apr_label = PaydayService.get_period_for_date(apr)
    jul_label = PaydayService.get_period_for_date(jul)

    labels = [p['label'] for p in VehicleService.get_trip_log_periods()]
    assert labels == [jan_label, jul_label]

    labels = [p['label'] for p in VehicleService.get_trip_log_periods(include_skipped=True)]
    assert labels == [jan_label, apr_label, jul_label]

    labels = [p['label'] for p in VehicleService.get_trip_log_periods(vehicle_id=other.id)]
    assert labels == [jul_label]

    # An early-month date before payday belongs to the previous month's period.
    early = date(2023, 6, 1)
    add_trip(other.id, early)
    db.session.commit()
    labels = [p['label'] for p in VehicleService.get_trip_log_periods(vehicle_id=other.id)]
    assert labels[0] == PaydayService.get_period_for_date(early)
