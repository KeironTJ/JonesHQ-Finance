from decimal import Decimal
from datetime import date

from extensions import db
from sqlalchemy import event
from models.accounts import Account
from models.categories import Category
from models.expenses import Expense
from models.trips import Trip
from models.transactions import Transaction
from models.vehicles import Vehicle
from services.finance.expense_service import ExpenseService
from services.finance.expense_sync_service import ExpenseSyncService


def _expense_data(**overrides):
    data = {
        'date': '2026-04-15',
        'description': 'Client travel',
        'expense_type': 'Mileage',
        'credit_card_id': '',
        'account_id': '',
        'covered_miles': '20',
        'rate_per_mile': '0.45',
        'days': '2',
        'total_cost': '18.00',
        'vehicle_registration': 'AB12 CDE',
        'paid_for': 'on',
        'submitted': 'on',
        'reimbursed': '',
    }
    data.update(overrides)
    return data


def test_create_expense_assigns_family_and_date_fields(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)

    expense = ExpenseService.create_expense(_expense_data())

    assert expense.family_id == family.id
    assert expense.month == '2026-04'
    assert expense.finance_year == '2026-2027'
    assert expense.week == '16-2026'
    assert expense.total_cost == Decimal('18.00')


def test_update_expense_rederives_finance_year(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    expense = ExpenseService.create_expense(_expense_data())

    updated = ExpenseService.update_expense(
        expense.id,
        _expense_data(date='2026-03-31', total_cost='12.50', submitted=''),
    )

    assert updated.month == '2026-03'
    assert updated.finance_year == '2025-2026'
    assert updated.total_cost == Decimal('12.50')
    assert updated.submitted is False


def test_delete_expense_is_family_scoped(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    expense = ExpenseService.create_expense(_expense_data())

    ExpenseService.delete_expense(expense.id)

    assert db.session.get(Expense, expense.id) is None


def test_bulk_delete_expenses_returns_deleted_count(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    first = ExpenseService.create_expense(_expense_data())
    second = ExpenseService.create_expense(_expense_data(description='Second'))

    deleted = ExpenseService.bulk_delete_expenses([first.id, second.id, 99999])

    assert deleted == 2
    assert db.session.get(Expense, first.id) is None
    assert db.session.get(Expense, second.id) is None


def test_delete_linked_transaction_clears_expense_foreign_key_first(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    account = Account(name='Current Account', account_type='Current', family_id=family.id)
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

    statements = []

    def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(db.engine, 'before_cursor_execute', capture_statement)
    try:
        ExpenseSyncService.bulk_delete_linked_transactions([expense.id])
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture_statement)

    update_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith('update expenses')
    )
    delete_index = next(
        index for index, statement in enumerate(statements)
        if statement.startswith('delete from transactions')
    )
    assert update_index < delete_index


def test_private_expense_hidden_from_other_family_members(app, family, monkeypatch, user):
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    expense = ExpenseService.create_expense(_expense_data(visibility='private'))

    assert expense.owner_id == user.id
    assert expense.is_private is True
    assert expense in family_query(Expense).all()

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)
    assert expense not in family_query(Expense).all()


def test_shared_expense_visible_to_everyone(app, family, monkeypatch, user):
    from utils.db_helpers import family_query

    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id)

    expense = ExpenseService.create_expense(_expense_data(visibility='shared'))

    monkeypatch.setattr('utils.db_helpers.get_current_user_id', lambda: user.id + 999)
    assert expense in family_query(Expense).all()


def test_fuel_expense_trip_sync_tracks_vehicle_and_removes_stale_trip(
    app, family, monkeypatch,
):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    monkeypatch.setattr(
        'services.vehicles.vehicle_service.VehicleService.calculate_trip_cost',
        lambda vehicle_id, miles, trip_date: (
            Decimal('2.00'), Decimal('1.00'), Decimal('10.00'),
        ),
    )
    first_vehicle = Vehicle(
        family_id=family.id, make='Example', model='One',
        registration='AA11 AAA',
    )
    second_vehicle = Vehicle(
        family_id=family.id, make='Example', model='Two',
        registration='BB22 BBB',
    )
    db.session.add_all([first_vehicle, second_vehicle])
    db.session.flush()
    expense = Expense(
        family_id=family.id, date=date(2026, 4, 15),
        description='Fuel stop', expense_type='Fuel',
        cost=Decimal('40.00'), total_cost=Decimal('40.00'),
        covered_miles=20, vehicle_registration=first_vehicle.registration,
    )
    db.session.add(expense)
    db.session.commit()

    ExpenseSyncService.reconcile(expense.id)
    trip = Trip.query.filter(
        Trip.journey_description.like(f'Expense #{expense.id}: %'),
    ).one()
    trip_id = trip.id
    assert trip.vehicle_id == first_vehicle.id

    expense.vehicle_registration = second_vehicle.registration
    expense.date = date(2026, 4, 16)
    expense.covered_miles = 35
    ExpenseSyncService.reconcile(expense.id)

    trip = Trip.query.filter(
        Trip.journey_description.like(f'Expense #{expense.id}: %'),
    ).one()
    assert trip.id == trip_id
    assert trip.vehicle_id == second_vehicle.id
    assert trip.date == date(2026, 4, 16)
    assert trip.total_miles == 35
    assert trip.fuel_cost == Decimal('40.00')

    expense.vehicle_registration = None
    ExpenseSyncService.reconcile(expense.id)
    assert Trip.query.filter(
        Trip.journey_description.like(f'Expense #{expense.id}: %'),
    ).count() == 0

    expense.vehicle_registration = second_vehicle.registration
    ExpenseSyncService.reconcile(expense.id)
    monkeypatch.setattr(
        ExpenseSyncService, '_ensure_bank_payment', lambda _expense: None,
    )
    expense.expense_type = 'Mileage'
    ExpenseSyncService.reconcile(expense.id)
    assert Trip.query.filter(
        Trip.journey_description.like(f'Expense #{expense.id}: %'),
    ).count() == 0

    expense.expense_type = 'Fuel'
    expense.vehicle_registration = second_vehicle.registration
    ExpenseSyncService.reconcile(expense.id)
    ExpenseSyncService.delete_fuel_trip_for_expense(expense)
    db.session.commit()
    assert Trip.query.filter(
        Trip.journey_description.like(f'Expense #{expense.id}: %'),
    ).count() == 0
