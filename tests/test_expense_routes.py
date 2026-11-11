from tests.auth_helpers import login_client
from datetime import date
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.expenses import Expense
from models.income import Income
from models.transactions import Transaction
from services.finance.expense_sync_service import ExpenseSyncService


def _login(client, user_id):
    login_client(client, user_id)


def _fail_statement_refresh(*_args, **_kwargs):
    raise RuntimeError('cleanup failed')


def _create_reimbursement_fixture(family, expense_dates_and_amounts):
    account = Account(
        name='Current Account', account_type='Current', family_id=family.id,
        balance=0,
    )
    category = Category(
        name='Reimbursement', category_type='income', family_id=family.id,
        head_budget='Income', sub_budget='Expense',
    )
    group = ExpenseReimbursementGroup(
        family_id=family.id, name='Default', mode='separate', is_default=True,
    )
    db.session.add_all([account, category, group])
    db.session.flush()
    expenses = [
        Expense(
            family_id=family.id, date=expense_date,
            description=f'Expense {index}', expense_type='Fuel',
            cost=amount, total_cost=amount,
            reimbursement_group_id=group.id,
        )
        for index, (expense_date, amount) in enumerate(expense_dates_and_amounts, start=1)
    ]
    db.session.add_all(expenses)
    db.session.commit()
    return group, expenses


def _create_card_fixture(family, account):
    card = CreditCard(
        family_id=family.id, card_name='Travel Card',
        annual_apr=Decimal('20.00'), monthly_apr=Decimal('1.67'),
        credit_limit=Decimal('5000.00'),
        default_payment_account_id=account.id,
    )
    card_category = Category(
        family_id=family.id, name='Travel Card', category_type='expense',
        head_budget='Credit Cards', sub_budget='Travel Card',
    )
    db.session.add_all([card, card_category])
    db.session.flush()
    return card


def test_expense_index_route_loads_for_authenticated_family(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/finance/expenses')

    assert response.status_code == 200
    assert b'Expenses' in response.data or b'expense' in response.data.lower()


def test_expense_index_shows_folded_payslip_badge(app, family, user):
    income = Income(
        family_id=family.id,
        pay_date=date(2026, 4, 15),
        gross_annual_income=Decimal('30000.00'),
        gross_monthly_income=Decimal('2500.00'),
        take_home=Decimal('2000.00'),
        expense_reimbursement_total=Decimal('25.00'),
    )
    expense = Expense(
        family_id=family.id,
        date=date(2026, 4, 10),
        description='Client lunch',
        expense_type='Food',
        cost=Decimal('25.00'),
        total_cost=Decimal('25.00'),
        income=income,
    )
    db.session.add(expense)
    db.session.commit()

    client = app.test_client()
    _login(client, user.id)

    response = client.get('/finance/expenses')

    assert response.status_code == 200
    assert b'Folded: \xc2\xa325.00' in response.data
    assert f'/finance/income/{income.id}/edit'.encode() in response.data


def test_expense_mileage_route_loads_empty_state(app, family, user):
    client = app.test_client()
    _login(client, user.id)

    response = client.get('/finance/expenses/mileage')

    assert response.status_code == 200


def test_delete_expense_with_linked_transaction(app, family, user):
    account = Account(
        name='Current Account', account_type='Current', family_id=family.id,
        balance=Decimal('-18.00'),
    )
    category = Category(name='Travel', category_type='Expense', family_id=family.id)
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id,
        account_id=account.id,
        category_id=category.id,
        amount=Decimal('-18.00'),
        transaction_date=date(2026, 4, 15),
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id,
        date=date(2026, 4, 15),
        description='Client travel',
        expense_type='Mileage',
        cost=Decimal('18.00'),
        total_cost=Decimal('18.00'),
        bank_transaction_id=transaction.id,
    )
    db.session.add(expense)
    db.session.commit()
    expense_id = expense.id
    transaction_id = transaction.id
    account_id = account.id
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expense_id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Expense deleted' in response.data
    assert db.session.get(Expense, expense_id) is None
    assert Transaction.query.filter_by(id=transaction_id).first() is None
    assert db.session.get(Account, account_id).balance == Decimal('0')


def test_delete_expense_cleans_linked_transaction_on_private_account(
    app, family, user,
):
    from models.trips import Trip
    from models.users import User
    from models.vehicles import Vehicle

    other_member = User(
        email='other@example.com', name='Other Member',
        family_id=family.id, role='member',
    )
    other_member.set_password('TestPass1!')
    db.session.add(other_member)
    db.session.flush()
    account = Account(
        name='Private Account', account_type='Current', family_id=family.id,
        owner_id=other_member.id, balance=Decimal('-18.00'),
    )
    vehicle = Vehicle(
        family_id=family.id, name='Private Car', make='Test', model='Car',
        registration='ZZ11ZZZ', owner_id=other_member.id,
    )
    category = Category(name='Travel', category_type='Expense', family_id=family.id)
    db.session.add_all([account, vehicle, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-18.00'), transaction_date=date(2026, 4, 15),
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id, date=date(2026, 4, 15),
        description='Client fuel', expense_type='Fuel',
        cost=Decimal('18.00'), total_cost=Decimal('18.00'),
        account_id=account.id, bank_transaction_id=transaction.id,
        vehicle_registration=vehicle.registration, covered_miles=5,
    )
    db.session.add(expense)
    db.session.flush()
    trip = Trip(
        family_id=family.id, vehicle_id=vehicle.id,
        date=expense.date, total_miles=5,
        journey_description=f'Expense #{expense.id}: Client fuel',
    )
    db.session.add(trip)
    db.session.commit()
    expense_id = expense.id
    transaction_id = transaction.id
    account_id = account.id
    trip_id = trip.id
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expense_id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Expense deleted' in response.data
    assert db.session.get(Expense, expense_id) is None
    assert Transaction.query.filter_by(id=transaction_id).first() is None
    assert db.session.get(Account, account_id).balance == Decimal('0')
    assert Trip.query.filter_by(id=trip_id).first() is None


def test_delete_expense_keeps_expense_when_linked_cleanup_fails(
    app, family, user, monkeypatch,
):
    account = Account(name='Current Account', account_type='Current', family_id=family.id)
    category = Category(name='Travel', category_type='Expense', family_id=family.id)
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-18.00'), transaction_date=date(2026, 4, 15),
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id, date=date(2026, 4, 15),
        description='Client travel', expense_type='Mileage',
        cost=Decimal('18.00'), total_cost=Decimal('18.00'),
        bank_transaction_id=transaction.id,
    )
    db.session.add(expense)
    db.session.commit()
    expense_id = expense.id
    transaction_id = transaction.id
    monkeypatch.setattr(
        'services.finance.credit_card_statement_service.CreditCardStatementService.refresh_after_changes',
        _fail_statement_refresh,
    )
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expense_id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Error deleting expense' in response.data
    assert db.session.get(Expense, expense_id) is not None
    assert db.session.get(Transaction, transaction_id) is not None


def test_bulk_delete_keeps_expense_when_linked_cleanup_fails(
    app, family, user, monkeypatch,
):
    account = Account(name='Current Account', account_type='Current', family_id=family.id)
    category = Category(name='Travel', category_type='Expense', family_id=family.id)
    db.session.add_all([account, category])
    db.session.flush()
    transaction = Transaction(
        family_id=family.id, account_id=account.id, category_id=category.id,
        amount=Decimal('-18.00'), transaction_date=date(2026, 4, 15),
    )
    db.session.add(transaction)
    db.session.flush()
    expense = Expense(
        family_id=family.id, date=date(2026, 4, 15),
        description='Client travel', expense_type='Mileage',
        cost=Decimal('18.00'), total_cost=Decimal('18.00'),
        bank_transaction_id=transaction.id,
    )
    db.session.add(expense)
    db.session.commit()
    expense_id = expense.id
    transaction_id = transaction.id
    monkeypatch.setattr(
        'services.finance.credit_card_statement_service.CreditCardStatementService.refresh_after_changes',
        _fail_statement_refresh,
    )
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        '/finance/expenses/bulk-delete-expenses',
        data={'expense_ids': str(expense_id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b'Error deleting expenses' in response.data
    assert db.session.get(Expense, expense_id) is not None
    assert db.session.get(Transaction, transaction_id) is not None


def test_update_expense_reconciles_old_and_new_periods(
    app, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [(date(2026, 4, 20), Decimal('10.00'))],
    )
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/update/{expenses[0].id}',
        data={
            'date': '2026-05-20',
            'description': 'Moved expense',
            'expense_type': 'Fuel',
            'total_cost': '10.00',
            'reimbursement_group_id': str(group.id),
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    reimbursements = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
    ).all()
    assert [(row.year_month, row.amount) for row in reimbursements] == [
        ('2026-05', Decimal('10.00')),
    ]


def test_delete_expense_reconciles_remaining_period_amount(
    app, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expenses[0].id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).one()
    assert reimbursement.amount == Decimal('20.00')


def test_bulk_delete_expenses_reconciles_period_amount(
    app, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [
            (date(2026, 4, 10), Decimal('10.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        '/finance/expenses/bulk-delete-expenses',
        data={'expense_ids': str(expenses[0].id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).one()
    assert reimbursement.amount == Decimal('20.00')


def test_deleting_last_expense_removes_unpaid_period_reimbursement(
    app, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [(date(2026, 4, 10), Decimal('10.00'))],
    )
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expenses[0].id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).first() is None


def test_deleting_last_card_expense_removes_generated_period_payoff(
    app, family, user, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, _ = _create_reimbursement_fixture(family, [])
    account = Account.query.filter_by(family_id=family.id).one()
    card = _create_card_fixture(family, account)
    expense = Expense(
        family_id=family.id, date=date(2026, 4, 10),
        description='Card travel expense', expense_type='Travel',
        cost=Decimal('25.00'), total_cost=Decimal('25.00'),
        credit_card_id=card.id, reimbursement_group_id=group.id,
    )
    db.session.add(expense)
    db.session.commit()

    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    ExpenseSyncService.reconcile_credit_card_payments(year_month='2026-04')
    payment = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id,
        transaction_type='Payment',
    ).one()
    bank_transaction_id = payment.bank_transaction_id
    client = app.test_client()
    _login(client, user.id)

    response = client.post(
        f'/finance/expenses/delete/{expense.id}',
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db.session.get(CreditCardTransaction, payment.id) is None
    assert db.session.get(Transaction, bank_transaction_id) is None


def test_card_payoff_reconciliation_updates_amount_date_and_account_balance(
    app, family, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [
            (date(2026, 4, 10), Decimal('25.00')),
            (date(2026, 4, 20), Decimal('20.00')),
        ],
    )
    account = Account.query.filter_by(family_id=family.id).one()
    card = _create_card_fixture(family, account)
    for expense in expenses:
        expense.expense_type = 'Travel'
        expense.credit_card_id = card.id
    db.session.commit()

    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).one()
    ExpenseSyncService.reconcile_credit_card_payments(year_month='2026-04')
    payment = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id,
        transaction_type='Payment',
    ).one()
    bank_transaction = db.session.get(Transaction, payment.bank_transaction_id)
    assert payment.amount == Decimal('45.00')

    expenses[0].total_cost = Decimal('15.00')
    expenses[0].cost = Decimal('15.00')
    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    reimbursement.transaction_date = date(2026, 5, 4)
    db.session.commit()
    ExpenseSyncService.reconcile_credit_card_payments(year_month='2026-04')

    assert reimbursement.amount == Decimal('35.00')
    assert payment.amount == Decimal('35.00')
    assert payment.date == date(2026, 5, 5)
    assert bank_transaction.amount == Decimal('-35.00')
    assert bank_transaction.transaction_date == date(2026, 5, 5)
    assert account.balance == Decimal('0.00')


def test_all_period_card_reconciliation_removes_payoff_without_reimbursement(
    app, family, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    group, expenses = _create_reimbursement_fixture(
        family, [(date(2026, 4, 10), Decimal('25.00'))],
    )
    account = Account.query.filter_by(family_id=family.id).one()
    card = _create_card_fixture(family, account)
    expense = expenses[0]
    expense.expense_type = 'Travel'
    expense.credit_card_id = card.id
    db.session.commit()

    ExpenseSyncService.reconcile_monthly_reimbursements(year_month='2026-04')
    reimbursement = Transaction.query.filter_by(
        payment_type='Expense Reimbursement',
        reimbursement_group_id=group.id,
        year_month='2026-04',
    ).one()
    ExpenseSyncService.reconcile_credit_card_payments(year_month='2026-04')
    payment = CreditCardTransaction.query.filter_by(
        credit_card_id=card.id,
        transaction_type='Payment',
    ).one()
    bank_transaction_id = payment.bank_transaction_id

    db.session.delete(reimbursement)
    db.session.delete(expense)
    db.session.commit()
    ExpenseSyncService.reconcile_credit_card_payments()

    assert db.session.get(CreditCardTransaction, payment.id) is None
    assert db.session.get(Transaction, bank_transaction_id) is None
