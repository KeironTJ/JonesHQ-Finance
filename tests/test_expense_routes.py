from extensions import db


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_expense_index_route_loads_for_authenticated_family(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/expenses')

    assert response.status_code == 200
    assert b'Expenses' in response.data or b'expense' in response.data.lower()


def test_expense_mileage_route_loads_empty_state(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/expenses/mileage')

    assert response.status_code == 200
