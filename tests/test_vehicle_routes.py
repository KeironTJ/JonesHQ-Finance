from extensions import db
from models.trip_template import TripTemplate
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
