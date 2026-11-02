from datetime import date, timedelta

from extensions import db
from models.trip_template import TripTemplate
from models.trip_schedule import TripSchedule
from models.trips import Trip
from models.users import User
from models.vehicles import Vehicle
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
    page = client.get(f'/vehicles/routines?schedule_id={schedule.id}')
    assert start_date.strftime('%a %d %b %Y') in page.get_data(as_text=True)

    response = client.post(
        f'/vehicles/trip-schedules/toggle/{schedule.id}',
        data={'is_active': '0'},
    )

    assert response.status_code == 302
    assert schedule.is_active is False
    assert Trip.query.filter_by(schedule_id=schedule.id, trip_status='planned').count() == 0


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
