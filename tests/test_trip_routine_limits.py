from datetime import date, timedelta

import pytest
from werkzeug.datastructures import MultiDict

from extensions import db
from models.family import Family
from models.trip_schedule import TripSchedule
from models.trips import Trip
from models.users import User
from models.vehicles import Vehicle
from services.platform.site_settings_service import SiteSettingsService
from services.vehicles.trip_schedule_service import TripScheduleService
from utils.db_helpers import family_query


@pytest.fixture
def routine_data(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = Vehicle(
        family_id=family.id, name='Routine car', make='Test', model='Routine',
        registration='LIMIT CAR',
    )
    db.session.add(vehicle)
    db.session.commit()
    SiteSettingsService.update({
        'trip_planning_max_days': '7', 'trip_active_routine_limit': '2',
    })
    return MultiDict([
        ('vehicle_id', str(vehicle.id)), ('name', 'Commute'), ('miles', '10'),
        ('frequency', 'weekly'), ('start_date', date.today().isoformat()),
        ('end_date', (date.today() + timedelta(days=7)).isoformat()),
        *[('days', str(day)) for day in range(7)],
    ])


@pytest.mark.parametrize('field', ['start_date', 'end_date'])
def test_rejects_dates_beyond_horizon_before_creating_rows(routine_data, field):
    routine_data[field] = (date.today() + timedelta(days=8)).isoformat()
    if field == 'start_date':
        routine_data['end_date'] = ''
    with pytest.raises(ValueError, match='7 days ahead'):
        TripScheduleService.create_schedule(routine_data)
    assert family_query(TripSchedule).count() == 0
    assert family_query(Trip).count() == 0


@pytest.mark.parametrize('end_date', ['', 'boundary'])
def test_boundary_is_inclusive_and_open_ended_respects_limit(routine_data, end_date):
    if not end_date:
        routine_data['end_date'] = ''
    schedule, _ = TripScheduleService.create_schedule(routine_data)
    trips = family_query(Trip).filter_by(schedule_id=schedule.id).order_by(Trip.date).all()
    assert [trip.date for trip in trips] == [
        date.today() + timedelta(days=offset) for offset in range(8)
    ]
    assert TripScheduleService.ensure_upcoming_trips() == set()


def test_quota_blocks_creation_and_resume_but_allows_editing_and_pausing(routine_data):
    first, _ = TripScheduleService.create_schedule(routine_data)
    second, _ = TripScheduleService.create_schedule(routine_data)
    with pytest.raises(ValueError, match='2 active trip routines'):
        TripScheduleService.create_schedule(routine_data)
    assert family_query(TripSchedule).count() == 2

    routine_data['name'] = 'Updated commute'
    TripScheduleService.update_schedule(second.id, routine_data)
    assert second.name == 'Updated commute'
    TripScheduleService.set_schedule_active(first.id, False)
    TripScheduleService.create_schedule(routine_data)
    with pytest.raises(ValueError, match='Pause or end'):
        TripScheduleService.set_schedule_active(first.id, True)
    assert first.is_active is False
    assert TripScheduleService.active_routine_count() == 2


def test_expired_routines_do_not_count_but_cannot_be_revived_over_quota(routine_data):
    routine_data['start_date'] = (date.today() - timedelta(days=2)).isoformat()
    routine_data['end_date'] = (date.today() - timedelta(days=1)).isoformat()
    expired, _ = TripScheduleService.create_schedule(routine_data)
    assert TripScheduleService.active_routine_count() == 0

    routine_data['end_date'] = date.today().isoformat()
    TripScheduleService.create_schedule(routine_data)
    TripScheduleService.create_schedule(routine_data)
    with pytest.raises(ValueError, match='2 active trip routines'):
        TripScheduleService.update_schedule(expired.id, routine_data)
    assert expired.end_date == date.today() - timedelta(days=1)


def test_quota_includes_private_routines_but_not_other_households(
    routine_data, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)
    other_member = User(family_id=family.id, name='Member', email='member@example.com')
    other_member.set_password('TestPass1!')
    other_family = Family(name='Other household')
    db.session.add_all([other_member, other_family])
    db.session.flush()
    private = Vehicle(
        family_id=family.id, owner_id=other_member.id,
        name='Private car', make='Test', model='Routine', registration='PRIVATE',
    )
    outside = Vehicle(
        family_id=other_family.id, name='Other car', make='Test', model='Routine',
        registration='OTHER',
    )
    db.session.add_all([private, outside])
    db.session.flush()
    for vehicle in (private, outside):
        db.session.add(TripSchedule(
            family_id=vehicle.family_id, vehicle_id=vehicle.id,
            name='Hidden routine', miles=1, weekdays='0', frequency='weekly',
            start_date=date.today(), is_active=True,
        ))
    db.session.commit()

    assert TripScheduleService.active_routine_count() == 1
    assert family_query(TripSchedule).count() == 0
    TripScheduleService.create_schedule(routine_data)
    assert TripScheduleService.active_routine_count() == 2
    with pytest.raises(ValueError, match='2 active trip routines'):
        TripScheduleService.create_schedule(routine_data)
    assert len(TripScheduleService.get_overview()) == 1


def test_lowered_horizon_preserves_trips_and_flags_routine_until_adjusted(routine_data):
    schedule, _ = TripScheduleService.create_schedule(routine_data)
    trip_ids = {trip.id for trip in family_query(Trip).all()}
    SiteSettingsService.update({'trip_planning_max_days': '3'})

    with pytest.raises(ValueError, match='3 days ahead'):
        TripScheduleService.ensure_upcoming_trips()
    assert {trip.id for trip in family_query(Trip).all()} == trip_ids
    assert '3 days ahead' in TripScheduleService.get_overview()[0]['limit_warning']

    routine_data['end_date'] = (date.today() + timedelta(days=3)).isoformat()
    TripScheduleService.update_schedule(schedule.id, routine_data)
    assert family_query(Trip).count() == 4
    assert TripScheduleService.get_overview()[0]['limit_warning'] is None


def test_lowered_quota_preserves_existing_trips_and_allows_pausing(routine_data):
    first, _ = TripScheduleService.create_schedule(routine_data)
    TripScheduleService.create_schedule(routine_data)
    trip_ids = {trip.id for trip in family_query(Trip).all()}
    SiteSettingsService.update({'trip_active_routine_limit': '1'})

    with pytest.raises(ValueError, match='1 active trip routines'):
        TripScheduleService.ensure_upcoming_trips()
    assert {trip.id for trip in family_query(Trip).all()} == trip_ids
    assert all(item['limit_warning'] for item in TripScheduleService.get_overview())
    TripScheduleService.set_schedule_active(first.id, False)
    assert TripScheduleService.ensure_upcoming_trips() == set()


def test_over_horizon_edit_and_legacy_refresh_fail_before_generation(routine_data):
    schedule, _ = TripScheduleService.create_schedule(routine_data)
    trip_ids = {trip.id for trip in family_query(Trip).all()}
    routine_data['end_date'] = '9999-12-31'
    with pytest.raises(ValueError, match='7 days ahead'):
        TripScheduleService.update_schedule(schedule.id, routine_data)
    assert schedule.end_date == date.today() + timedelta(days=7)

    schedule.end_date = date(9999, 12, 31)
    db.session.commit()
    with pytest.raises(ValueError, match='7 days ahead'):
        TripScheduleService.ensure_upcoming_trips()
    assert {trip.id for trip in family_query(Trip).all()} == trip_ids
    TripScheduleService.set_schedule_active(schedule.id, False)
    with pytest.raises(ValueError, match='7 days ahead'):
        TripScheduleService.set_schedule_active(schedule.id, True)
    assert schedule.is_active is False
