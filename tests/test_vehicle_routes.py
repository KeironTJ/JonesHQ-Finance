from datetime import date, timedelta

from extensions import db
from models.fuel import FuelRecord
from models.trip_template import TripTemplate
from models.trip_schedule import TripSchedule
from models.trips import Trip
from models.users import User
from models.vehicles import Vehicle
from services.platform.site_settings_service import SiteSettingsService
from tests.auth_helpers import login_client


def test_trip_template_routes_create_update_and_delete(app, family, user):
    vehicle = Vehicle(
        family_id=family.id,
        name='Saved Journey Car',
        make='Test',
        model='Trip',
        registration='SJ12 CAR',
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.post('/vehicles/trip-templates/add', data={
        'vehicle_id': str(vehicle.id),
        'name': 'Work',
        'trip_type': 'business',
        'miles': '24',
        'journey_description': 'Office',
    })
    template = TripTemplate.query.filter_by(family_id=family.id).one()

    assert response.status_code == 302
    assert template.name == 'Work'

    response = client.post(
        f'/vehicles/trip-templates/update/{template.id}',
        data={
            'vehicle_id': str(vehicle.id),
            'name': 'Updated work',
            'trip_type': 'business',
            'miles': '26',
            'journey_description': 'New office route',
        },
    )
    assert response.status_code == 302
    assert template.name == 'Updated work'
    assert template.miles == 26

    response = client.post(f'/vehicles/trip-templates/delete/{template.id}')
    assert response.status_code == 302
    assert TripTemplate.query.count() == 0


def test_vehicle_overview_shows_trip_forecast_and_recent_history(app, family, user):
    vehicle = Vehicle(
        family_id=family.id,
        name='Overview Car',
        make='Test',
        model='Summary',
        registration='OV12 CAR',
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    today = date.today()
    db.session.add_all([
        Trip(
            family_id=family.id,
            vehicle_id=vehicle.id,
            date=today,
            total_miles=18,
            personal_miles=18,
            trip_status='actual',
        ),
        Trip(
            family_id=family.id,
            vehicle_id=vehicle.id,
            date=today + timedelta(days=7),
            total_miles=40,
            personal_miles=40,
            trip_status='planned',
            trip_cost=7.25,
        ),
        FuelRecord(
            family_id=family.id,
            vehicle_id=vehicle.id,
            date=today,
            mileage=1000,
            cost=42.50,
            gallons=8,
        ),
    ])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.get('/vehicles')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Driving overview' in html
    assert 'Trips this year' in html
    assert 'Planned trips' in html
    assert 'Planned trip fuel' in html
    assert 'Forecast refuels' in html
    assert 'Recent history' in html
    assert '£7.25' in html
    assert '£42.50' in html

    overview_response = client.get('/vehicles/driving-overview')
    overview_html = overview_response.get_data(as_text=True)
    assert overview_response.status_code == 200
    assert 'Six-month driving and fuel history' in overview_html
    assert 'Vehicle comparison' in overview_html
    assert 'Upcoming trips' in overview_html
    assert 'Forecast refuels' in overview_html
    assert 'Overview Car' in overview_html
    assert 'Planned trip' in overview_html
    assert 'fleetDrivingChartData' in overview_html


def test_trip_schedule_route_creates_and_pauses_planned_trips(app, family, user):
    vehicle = Vehicle(
        family_id=family.id,
        name='Routine Route Car',
        make='Test',
        model='Trip',
        registration='RR12 CAR',
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    start_date = date.today() + timedelta(days=30)

    response = client.post('/vehicles/trip-schedules/add', data={
        'vehicle_id': str(vehicle.id),
        'name': 'School run routine',
        'trip_type': 'personal',
        'miles': '8',
        'journey_description': 'School',
        'frequency': 'weekly',
        'start_date': start_date.isoformat(),
        'end_date': start_date.isoformat(),
        'days': str(start_date.weekday()),
    })
    schedule = TripSchedule.query.filter_by(family_id=family.id).one()

    assert response.status_code == 302
    assert Trip.query.filter_by(schedule_id=schedule.id, trip_status='planned').count() == 1

    page = client.get('/vehicles/routines')
    assert page.status_code == 200
    assert 'School run routine' in page.get_data(as_text=True)
    assert f'data-href="/vehicles/routines?schedule_id={schedule.id}#occurrences"' in page.get_data(as_text=True)
    page = client.get(f'/vehicles/routines?schedule_id={schedule.id}')
    assert 'data-href="/vehicles/routines"' in page.get_data(as_text=True)
    assert start_date.strftime('%a %d %b %Y') in page.get_data(as_text=True)

    response = client.post(
        f'/vehicles/trip-schedules/toggle/{schedule.id}',
        data={'is_active': '0'},
    )

    assert response.status_code == 302
    assert schedule.is_active is False
    assert Trip.query.filter_by(schedule_id=schedule.id, trip_status='planned').count() == 0


def test_routine_page_shows_limits_and_preserves_trips_after_limit_reduction(app, family, user):
    vehicle = Vehicle(
        family_id=family.id, name='Limits car', make='Test', model='Routine',
        registration='LIMIT ROUTE',
    )
    db.session.add(vehicle)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    today = date.today()
    data = {
        'vehicle_id': str(vehicle.id), 'name': 'Bounded routine', 'miles': '10',
        'frequency': 'weekly', 'start_date': today.isoformat(),
        'end_date': (today + timedelta(days=1801)).isoformat(),
        'days': str(today.weekday()),
    }

    response = client.post('/vehicles/trip-schedules/add', data=data, follow_redirects=True)
    html = response.get_data(as_text=True)
    assert '1,800 days ahead' in html
    assert TripSchedule.query.count() == 0
    assert '0 / 25 active routines' in html
    latest = (today + timedelta(days=1800)).isoformat()
    assert f'max="{latest}"' in html

    data['end_date'] = (today + timedelta(days=14)).isoformat()
    assert client.post('/vehicles/trip-schedules/add', data=data).status_code == 302
    trip_ids = {trip.id for trip in Trip.query.all()}
    assert len(trip_ids) == 3
    SiteSettingsService.update({'trip_planning_max_days': '7'})

    response = client.get('/vehicles/routines')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'New routine trips are paused' in html
    assert 'Existing trips have been kept' in html
    assert 'Needs adjustment' in html
    assert '7 days ahead' in html
    assert {trip.id for trip in Trip.query.all()} == trip_ids


def test_completed_routine_occurrence_can_be_edited_or_skipped(app, family, user):
    vehicle = Vehicle(
        family_id=family.id,
        name='Completed Routine Car',
        make='Test',
        model='Trip',
        registration='CR12 CAR',
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    today = date.today()

    client.post('/vehicles/trip-schedules/add', data={
        'vehicle_id': str(vehicle.id),
        'name': 'Completed commute',
        'trip_type': 'personal',
        'miles': '10',
        'journey_description': 'Office',
        'frequency': 'weekly',
        'start_date': today.isoformat(),
        'end_date': today.isoformat(),
        'days': str(today.weekday()),
    })
    schedule = TripSchedule.query.filter_by(family_id=family.id).one()
    trip = Trip.query.filter_by(schedule_id=schedule.id).one()
    client.post(f'/vehicles/trips/{trip.id}/confirm')

    page = client.get(f'/vehicles/routines?schedule_id={schedule.id}')
    html = page.get_data(as_text=True)
    assert 'Completed' in html
    assert f'data-update-url="/vehicles/trip/update/{trip.id}"' in html
    assert f'action="/vehicles/trips/{trip.id}/skip"' in html
    assert 'Didn&#39;t happen' in html or "Didn't happen" in html

    response = client.post(f'/vehicles/trips/{trip.id}/skip')
    assert response.status_code == 302
    assert trip.trip_status == 'skipped'


def test_trip_page_renders_saved_journeys_and_bulk_preview(app, family, user):
    vehicle = Vehicle(
        family_id=family.id,
        name='Trip Page Car',
        make='Test',
        model='Trip',
        registration='TP12 CAR',
        owner_id=user.id,
        is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    db.session.add(TripTemplate(
        family_id=family.id,
        vehicle_id=vehicle.id,
        name='School run',
        trip_type='personal',
        miles=8,
        journey_description='School',
    ))
    db.session.commit()

    client = app.test_client()
    login_client(client, user.id)
    response = client.get('/vehicles/trips')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'School run' in html
    assert 'bulkTripPreview' in html
    assert 'Review dates' in html
    assert 'Saved Journeys' in html

    other_user = User(
        email='trip-viewer@example.com',
        name='Trip Viewer',
        family_id=family.id,
        role='admin',
    )
    other_user.set_password('TestPass1!')
    db.session.add(other_user)
    db.session.commit()
    login_client(client, other_user.id)
    private_response = client.get('/vehicles/trips')

    assert private_response.status_code == 200
    assert 'School run' not in private_response.get_data(as_text=True)


def test_trip_log_respects_pay_period_and_hides_skipped(app, family, user):
    vehicle = Vehicle(
        family_id=family.id, name='Period Car', make='Test', model='Trip',
        registration='PC12 CAR', is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    today = date.today()
    for description, day, status in (
        ('Done today', today, 'actual'),
        ('Skipped today', today, 'skipped'),
        ('Far future plan', today + timedelta(days=80), 'planned'),
    ):
        db.session.add(Trip(
            family_id=family.id, vehicle_id=vehicle.id, date=day,
            total_miles=5, personal_miles=5, trip_status=status,
            journey_description=description,
        ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    html = client.get('/vehicles/trips').get_data(as_text=True)
    assert 'Done today' in html
    assert 'Skipped today' not in html
    assert 'Far future plan' not in html

    html = client.get('/vehicles/trips?show_skipped=1').get_data(as_text=True)
    assert 'Skipped today' in html

    html = client.get('/vehicles/trips?payday_period_trip=all').get_data(as_text=True)
    assert 'Far future plan' in html
    assert 'Confirm due (' not in html


def test_confirm_due_route_confirms_past_planned_trips(app, family, user):
    vehicle = Vehicle(
        family_id=family.id, name='Due Car', make='Test', model='Trip',
        registration='DU12 CAR', is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    past = Trip(
        family_id=family.id, vehicle_id=vehicle.id,
        date=date.today() - timedelta(days=1),
        total_miles=5, personal_miles=5, trip_status='planned',
    )
    future = Trip(
        family_id=family.id, vehicle_id=vehicle.id,
        date=date.today() + timedelta(days=1),
        total_miles=5, personal_miles=5, trip_status='planned',
    )
    db.session.add_all([past, future])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    assert 'Confirm due (1)' in client.get('/vehicles/trips?payday_period_trip=all').get_data(as_text=True)
    response = client.post('/vehicles/trips/confirm-due')

    assert response.status_code == 302
    assert past.trip_status == 'actual'
    assert future.trip_status == 'planned'


def test_clear_future_route_removes_manual_trips(app, family, user):
    vehicle = Vehicle(
        family_id=family.id, name='Clear Car', make='Test', model='Trip',
        registration='CL12 CAR', is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    future = Trip(
        family_id=family.id, vehicle_id=vehicle.id,
        date=date.today() + timedelta(days=3), total_miles=5, personal_miles=5,
    )
    db.session.add(future)
    db.session.commit()
    future_id = future.id
    client = app.test_client()
    login_client(client, user.id)

    assert 'clearFutureTripsModal' in client.get('/vehicles/trips').get_data(as_text=True)
    response = client.post('/vehicles/trips/clear-future', data={
        'from_date': (date.today() + timedelta(days=1)).isoformat(),
        'vehicle_id': str(vehicle.id),
        'routine_mode': 'keep',
    })

    assert response.status_code == 302
    assert db.session.get(Trip, future_id) is None


def test_journeys_page_and_trip_subnav(app, family, user):
    vehicle = Vehicle(
        family_id=family.id, name='Journey Page Car', make='Test', model='Trip',
        registration='JP12 CAR', is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    db.session.add(TripTemplate(
        family_id=family.id, vehicle_id=vehicle.id, name='Gym run',
        trip_type='personal', miles=6,
    ))
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)

    response = client.get('/vehicles/journeys')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Gym run' in html
    assert 'tripTemplateForm' in html

    for path in ('/vehicles/trips', '/vehicles/routines', '/vehicles/journeys'):
        page = client.get(path).get_data(as_text=True)
        assert 'vehicle-subnav' in page
        assert 'href="/vehicles/routines"' in page
        assert 'href="/vehicles/journeys"' in page
    trip_html = client.get('/vehicles/trips').get_data(as_text=True)
    assert 'tripTemplatesModal' not in trip_html
    assert 'Gym run' in trip_html  # still offered in the Add Trip journey picker

    response = client.post('/vehicles/trip-templates/add', data={
        'vehicle_id': str(vehicle.id), 'name': 'Shop', 'trip_type': 'personal', 'miles': '3',
    })
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/vehicles/journeys')


def test_trip_log_period_dropdown_omits_empty_periods(app, family, user):
    from services.finance.payday_service import PaydayService

    vehicle = Vehicle(
        family_id=family.id, name='Sparse Car', make='Test', model='Trip',
        registration='SP12 CAR', is_active=True,
    )
    db.session.add(vehicle)
    db.session.flush()
    old_day = date.today() - timedelta(days=200)
    db.session.add(Trip(
        family_id=family.id, vehicle_id=vehicle.id, date=old_day,
        total_miles=5, personal_miles=5, journey_description='Old trip',
    ))
    db.session.commit()
    old_label = PaydayService.get_period_for_date(old_day)
    current_label = PaydayService.get_period_for_date(date.today())
    client = app.test_client()
    login_client(client, user.id)

    html = client.get('/vehicles/trips').get_data(as_text=True)

    assert f'value="{old_label}" selected' in html
    assert f'value="{current_label}"' not in html
    assert html.count('<option value="20') == 1
    assert 'Old trip' in html
