from datetime import date
from html.parser import HTMLParser

import pytest
from flask import g

from extensions import db
from models.accounts import Account
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.expenses import Expense
from models.fuel import FuelRecord
from models.income import Income
from models.loan_payments import LoanPayment
from models.loans import Loan
from models.plans import Plan, PlanItem
from models.vehicles import Vehicle
from tests.auth_helpers import login_client


class ActionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons = []
        self.csrf_token = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'button' and 'data-action-url' in attributes:
            self.buttons.append(attributes)
        if tag == 'input' and attributes.get('name') == 'csrf_token':
            self.csrf_token = attributes.get('value')


@pytest.mark.parametrize('script_name', ['', '/mounted'])
def test_finance_action_buttons_use_registered_urls(app, family, user, script_name, monkeypatch):
    today = date.today()
    account = Account(family_id=family.id, name='Current', account_type='Current', balance=0, is_active=True)
    card = CreditCard(
        family_id=family.id, card_name='Card', annual_apr=0, monthly_apr=0,
        credit_limit=5000, current_balance=0, is_active=True,
    )
    inactive_card = CreditCard(
        family_id=family.id, card_name='Old card', annual_apr=0, monthly_apr=0,
        credit_limit=5000, current_balance=0, is_active=False,
    )
    vehicle = Vehicle(
        family_id=family.id, name='Car', make='Test', model='Car',
        registration='TEST CAR', tank_size=10, fuel_type='Petrol', is_active=True,
    )
    inactive_vehicle = Vehicle(
        family_id=family.id, name='Old car', make='Test', model='Car',
        registration='OLD CAR', tank_size=10, fuel_type='Petrol', is_active=False,
    )
    group = ExpenseReimbursementGroup(family_id=family.id, name='Work', mode='separate')
    plan = Plan(family_id=family.id, title='Plan')
    expense = Expense(
        family_id=family.id, date=today, description='Lunch', expense_type='Food',
        cost=25, total_cost=25,
    )
    income = Income(
        family_id=family.id, pay_date=today, tax_year='2026-2027',
        gross_annual_income=30000, gross_monthly_income=2500, take_home=2000,
    )
    loan = Loan(
        family_id=family.id, name='Loan', loan_value=1000, principal=1000,
        current_balance=1000, annual_apr=12, monthly_apr=1, monthly_payment=100,
        start_date=date(2026, 1, 1), end_date=date(2027, 1, 1), term_months=12,
    )
    item = PlanItem(family_id=family.id, plan=plan, title='Purchase')
    db.session.add_all([account, card, inactive_card, vehicle, inactive_vehicle, group, expense, income, loan, plan, item])
    db.session.flush()
    card_transaction = CreditCardTransaction(
        family_id=family.id, credit_card_id=card.id, date=today,
        transaction_type='Purchase', item='Purchase', amount=-10,
    )
    fuel = FuelRecord(
        family_id=family.id, vehicle_id=vehicle.id, date=today, mileage=1000,
        price_per_litre=150, cost=42, gallons=8, actual_miles=0,
    )
    payment = LoanPayment(
        family_id=family.id, loan_id=loan.id, date=today, year_month=today.strftime('%Y-%m'),
        period=1, opening_balance=1000, payment_amount=100, interest_charge=10,
        amount_paid_off=90, closing_balance=910, is_paid=False,
    )
    db.session.add_all([card_transaction, fuel, payment])
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    environ = {'SCRIPT_NAME': script_name}

    pages = [
        ('/finance/accounts', [f'/finance/accounts/{account.id}/delete']),
        ('/finance/credit-cards', [
            f'/finance/credit-cards/{card.id}/delete',
            f'/finance/credit-cards/{inactive_card.id}/delete',
        ]),
        (f'/finance/credit-cards/{card.id}', [f'/finance/credit-cards/transaction/{card_transaction.id}/link-plan']),
        ('/finance/expenses', [
            f'/finance/expenses/update/{expense.id}',
            *[f'/finance/expenses/toggle/{expense.id}/{field}' for field in ('paid_for', 'submitted', 'reimbursed')],
        ]),
        ('/finance/expenses/groups', [f'/finance/expenses/groups/{group.id}/update']),
        ('/finance/income', [f'/finance/income/toggle/{income.id}/paid']),
        (f'/finance/loans/{loan.id}', [f'/finance/loans/{loan.id}/payment/{payment.id}/toggle-paid']),
        ('/finance/vehicles', [f'/finance/vehicles/update/{vehicle.id}']),
        ('/finance/vehicles?tab=manage', [
            f'/finance/vehicles/update/{vehicle.id}',
            f'/finance/vehicles/update/{inactive_vehicle.id}',
        ]),
        ('/finance/vehicles/fuel?payday_period=all', [f'/finance/vehicles/fuel/update/{fuel.id}']),
    ]
    adapter = app.url_map.bind('localhost')
    for path, expected in pages:
        response = client.get(path, environ_overrides=environ)
        assert response.status_code == 200, path
        parser = ActionParser()
        parser.feed(response.get_data(as_text=True))
        actions = {button['data-action-url'] for button in parser.buttons}
        for action in expected:
            assert script_name + action in actions, path
            assert adapter.match(action, method='POST')
        assert 'dataset.actionUrl' in response.get_data(as_text=True)

    for path, expected in (
        ('/finance/income/add', '/finance/income/calculate-preview'),
        ('/finance/vehicles/trips', '/finance/vehicles/trips/bulk-delete'),
    ):
        response = client.get(path, environ_overrides=environ)
        assert response.status_code == 200, path
        assert f'"{script_name}{expected}"' in response.get_data(as_text=True)
        assert adapter.match(expected, method='POST')

    for action in (
        f'/finance/expenses/toggle/{expense.id}/paid_for',
        f'/finance/expenses/toggle/{expense.id}/submitted',
        f'/finance/expenses/toggle/{expense.id}/reimbursed',
        f'/finance/income/toggle/{income.id}/paid',
    ):
        response = client.post(action, environ_overrides=environ)
        assert response.status_code == 200
        assert response.get_json()['value'] is True
    response = client.post(
        f'/finance/credit-cards/transaction/{card_transaction.id}/link-plan',
        environ_overrides=environ, data={'plan_item_id': str(item.id)},
    )
    assert response.status_code == 302
    assert item.credit_card_transaction_id == card_transaction.id

    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_token', None)
    for page, action, payload in (
        (f'/finance/loans/{loan.id}', f'/finance/loans/{loan.id}/payment/{payment.id}/toggle-paid', {}),
        ('/finance/income/add', '/finance/income/calculate-preview', {
            'gross_annual': '30000', 'tax_code': '1257L',
        }),
    ):
        response = client.get(page, environ_overrides=environ)
        parser = ActionParser()
        html = response.get_data(as_text=True)
        parser.feed(html)
        assert parser.csrf_token
        assert f"'X-CSRFToken': '{parser.csrf_token}'" in html
        assert client.post(action, environ_overrides=environ, json=payload).status_code == 400
        response = client.post(
            action, environ_overrides=environ, json=payload,
            headers={'X-CSRFToken': parser.csrf_token},
        )
        assert response.status_code == 200, (action, response.get_data(as_text=True))
        assert response.get_json()['success'] is True
    assert payment.is_paid is True
