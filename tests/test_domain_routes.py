from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.childcare import Child
from models.loan_payments import LoanPayment
from models.loans import Loan
from models.transactions import Transaction


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_loan_payment_toggle_route_syncs_bank_payment(app, family, user):
    family_id = family.id
    user_id = user.id
    account = Account(
        family_id=family_id, name='Loan Account', account_type='Joint',
        balance=0, is_active=True
    )
    category = Category(
        family_id=family_id, name='Loan Payment', head_budget='Loans',
        sub_budget='Payment', category_type='expense'
    )
    db.session.add_all([account, category])
    db.session.flush()
    loan = Loan(
        family_id=family_id, name='Route Loan', loan_value=1000,
        principal=1000, current_balance=1000, annual_apr=12,
        monthly_apr=1, monthly_payment=100, start_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1), term_months=12
    )
    db.session.add(loan)
    db.session.flush()
    bank_transaction = Transaction(
        family_id=family_id, account_id=account.id, category_id=category.id,
        amount=Decimal('-100'), transaction_date=date(2026, 1, 15), is_paid=False
    )
    db.session.add(bank_transaction)
    db.session.flush()
    payment = LoanPayment(
        family_id=family_id, loan_id=loan.id, date=date(2026, 1, 15),
        year_month='2026-01', period=1, opening_balance=1000,
        payment_amount=100, interest_charge=10, amount_paid_off=90,
        closing_balance=910, is_paid=False, bank_transaction_id=bank_transaction.id
    )
    db.session.add(payment)
    db.session.commit()
    loan_id = loan.id
    payment_id = payment.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(f'/loans/{loan_id}/payment/{payment_id}/toggle-paid')

    assert response.status_code == 200
    db.session.refresh(payment)
    db.session.refresh(bank_transaction)
    assert payment.is_paid is True
    assert bank_transaction.is_paid is True


def test_childcare_bulk_route_returns_zero_for_empty_month(app, family, user):
    family_id = family.id
    user_id = user.id
    child = Child(
        family_id=family_id, name='Route Child', transaction_day=28, is_active=True
    )
    db.session.add(child)
    db.session.commit()
    child_id = child.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post('/childcare/bulk_create_transactions', json={
        'year': 2026,
        'month': 1,
        'transactions': [{'child_id': child_id, 'account_id': 1}],
    })

    assert response.status_code == 200
    assert response.get_json()['created'] == 0
