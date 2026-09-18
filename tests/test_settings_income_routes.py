from decimal import Decimal

from extensions import db
from models.income import Income
from models.settings import Settings


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_settings_preference_route_persists_json_value(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/settings/save_preference', json={
        'key': 'dashboard.test_expanded',
        'value': True,
    })

    assert response.status_code == 200
    assert response.get_json() == {'success': True}
    setting = Settings.query.filter_by(key='dashboard.test_expanded').one()
    assert setting.value == 'True'
    assert setting.setting_type == 'boolean'


def test_income_add_route_creates_income_record(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.post('/income/add', data={
        'person': 'Household',
        'pay_date': '2026-01-15',
        'gross_annual': '60000',
        'employer_pension_pct': '5',
        'employee_pension_pct': '3',
        'tax_code': '1257L',
        'avc': '0',
        'other': '0',
        'deposit_account_id': '',
        'source': 'Employer',
        'create_transaction': '',
    })

    assert response.status_code == 302
    income = Income.query.one()
    assert income.family_id == family.id
    assert income.take_home > Decimal('0')
