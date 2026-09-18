from datetime import date
from decimal import Decimal

from extensions import db
from models.mortgage import MortgageProduct
from models.pension_snapshots import PensionSnapshot
from models.pensions import Pension
from models.property import Property


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_mortgage_property_create_route(app, family, user):
    family_id = family.id
    user_id = user.id
    client = app.test_client()
    _login(client, user_id)

    response = client.post('/mortgage/property/create', data={
        'address': 'Route Property',
        'purchase_date': '2020-01-01',
        'purchase_price': '250000',
        'current_valuation': '300000',
        'annual_appreciation_rate': '3.5',
        'is_primary_residence': 'on',
    })

    assert response.status_code == 302
    property_obj = Property.query.one()
    assert property_obj.family_id == family_id
    assert property_obj.address == 'Route Property'


def test_pension_create_and_snapshot_routes(app, family, user):
    family_id = family.id
    user_id = user.id
    client = app.test_client()
    _login(client, user_id)

    response = client.post('/pensions/add', data={
        'person': 'Household',
        'provider': 'Route Pension',
        'account_number': 'RP-1',
        'current_value': '5000',
        'contribution_rate': '5',
        'employer_contribution': '3',
        'is_active': 'on',
        'retirement_age': '65',
        'monthly_contribution': '100',
    })
    assert response.status_code == 302
    pension = Pension.query.one()
    assert pension.family_id == family_id

    response = client.post(f'/pensions/{pension.id}/snapshots/add', data={
        'review_date': '2026-01-15',
        'value': '5500',
    })
    assert response.status_code == 302
    snapshot = PensionSnapshot.query.one()
    assert snapshot.family_id == family_id
    assert snapshot.value == Decimal('5500')
