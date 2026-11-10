from datetime import date, timedelta
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.fuel import FuelRecord
from models.transactions import Transaction
from models.trips import Trip
from models.vehicles import Vehicle
from services.finance.monthly_balance_service import MonthlyBalanceService
from services.vehicles.fuel_forecasting_service import FuelForecastingService
from services.vehicles.vehicle_service import VehicleService
from tests.auth_helpers import login_client
from utils.db_helpers import family_query


@pytest.fixture
def vehicle(app, family, monkeypatch):
    monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family.id)
    vehicle = Vehicle(
        family_id=family.id, name='Forecast Car', make='Test', model='Test',
        registration='FC12 AST', tank_size=10, refuel_threshold_pct=95,
    )
    db.session.add(vehicle)
    db.session.commit()
    return vehicle


@pytest.fixture
def forecast_vehicle(vehicle, monkeypatch):
    monkeypatch.setattr(
        FuelForecastingService, 'get_average_mpg', staticmethod(lambda _: 10.0),
    )
    monkeypatch.setattr(
        FuelForecastingService, 'get_average_fuel_price',
        staticmethod(lambda _: Decimal('150')),
    )
    return vehicle


def add_fill(vehicle, day, gallons=10, partial=False, mileage=1000):
    fill = FuelRecord(
        family_id=vehicle.family_id, vehicle_id=vehicle.id, date=day,
        price_per_litre=150, mileage=mileage, cost=30, gallons=gallons,
        is_partial_fill=partial, actual_miles=0, actual_cumulative_miles=0,
    )
    db.session.add(fill)
    db.session.commit()
    return fill


def add_trip(vehicle, day, miles):
    trip = Trip(
        family_id=vehicle.family_id, vehicle_id=vehicle.id, date=day,
        total_miles=miles, personal_miles=miles,
    )
    db.session.add(trip)
    db.session.commit()
    return trip


def add_fuel_account(vehicle):
    account = Account(
        family_id=vehicle.family_id, name='Fuel account', account_type='Current',
        balance=0, is_active=True,
    )
    category = Category(
        family_id=vehicle.family_id, name='Transportation - Fuel',
        category_type='Expense',
    )
    db.session.add_all([account, category])
    db.session.flush()
    vehicle.fuel_account_id = account.id
    db.session.commit()
    return account, category


def forecasts(vehicle):
    return family_query(Transaction).filter_by(is_forecasted=True).filter(
        Transaction.description == f'Forecasted fuel - {vehicle.registration}',
    ).order_by(Transaction.transaction_date).all()


@pytest.mark.parametrize('threshold,miles,expected', [
    (95, 14, False),
    (95, 15, True),
    (95, 16, True),
    (90, 10, True),
    (100, 20, True),
])
def test_current_trip_threshold_and_date(forecast_vehicle, threshold, miles, expected):
    vehicle = forecast_vehicle
    vehicle.refuel_threshold_pct = threshold
    add_fill(vehicle, date(2026, 9, 1))
    previous = add_trip(vehicle, date(2026, 9, 2), 80)
    current = add_trip(vehicle, date(2026, 12, 10), miles)

    predictions = FuelForecastingService.predict_refills(vehicle.id)
    assert bool(predictions) is expected
    levels = FuelForecastingService.get_trip_tank_levels(vehicle.id)
    assert levels[previous.id] == 20.0
    if expected:
        assert predictions == [{
            'date': current.date, 'gallons': 8.0, 'cost': 54.55,
            'tank_level_before': 2.0, 'trigger_trip_date': current.date,
            'trigger_trip_id': current.id,
        }]
        assert levels[current.id] == pytest.approx(100 - miles)
    else:
        assert levels[current.id] == pytest.approx(20 - miles)


def test_hidden_historical_predictions_cannot_seed_a_partial_fill(forecast_vehicle):
    vehicle = forecast_vehicle
    add_fill(vehicle, date(2026, 6, 1))
    add_trip(vehicle, date(2026, 6, 2), 80)
    drained = add_trip(vehicle, date(2026, 6, 3), 20)
    add_fill(vehicle, date(2026, 9, 1), gallons=1, partial=True)
    current = add_trip(vehicle, date(2026, 9, 2), 10)

    predictions = FuelForecastingService.predict_refills(vehicle.id)
    assert len(predictions) == 1
    assert predictions[0]['date'] == current.date
    assert predictions[0]['gallons'] == 9.0
    assert predictions[0]['cost'] == 61.37
    levels = FuelForecastingService.get_trip_tank_levels(vehicle.id)
    assert levels[drained.id] == 0.0
    assert levels[current.id] == 90.0
    assert FuelForecastingService.get_tank_status(vehicle.id)['gallons_remaining'] == 0


def test_full_fill_supersedes_older_forecasts_and_same_day_fills_are_ordered(forecast_vehicle):
    vehicle = forecast_vehicle
    add_fill(vehicle, date(2026, 6, 1))
    add_trip(vehicle, date(2026, 6, 2), 80)
    add_trip(vehicle, date(2026, 6, 3), 20)
    add_fill(vehicle, date(2026, 9, 1), gallons=1, partial=True)
    add_fill(vehicle, date(2026, 9, 1), partial=False)
    add_trip(vehicle, date(2026, 9, 1), 10)
    assert FuelForecastingService.predict_refills(vehicle.id) == []


@pytest.mark.parametrize('miles,expected_gallons,expected_level', [
    (95, [], 5.0),
    (150, [9.5], 45.0),
    (250, [9.5, 9.5], 40.0),
])
def test_long_trips_forecast_nonzero_same_day_topups(
    forecast_vehicle, miles, expected_gallons, expected_level,
):
    vehicle = forecast_vehicle
    add_fill(vehicle, date(2026, 9, 1))
    trip = add_trip(vehicle, date(2026, 9, 2), miles)
    predictions = FuelForecastingService.predict_refills(vehicle.id)
    assert [p['gallons'] for p in predictions] == expected_gallons
    assert all(p['date'] == trip.date and p['cost'] > 0 for p in predictions)
    assert FuelForecastingService.get_trip_tank_levels(vehicle.id)[trip.id] == expected_level


def test_sync_sums_same_day_refills_and_preserves_actual_transactions(forecast_vehicle):
    vehicle = forecast_vehicle
    account, category = add_fuel_account(vehicle)
    add_fill(vehicle, date(2026, 9, 1))
    for _ in range(3):
        add_trip(vehicle, date(2026, 9, 2), 80)
    actual = Transaction(
        family_id=vehicle.family_id, account_id=account.id, category_id=category.id,
        transaction_date=date(2026, 9, 1), amount=-30,
        description=f'Fuel - {vehicle.registration}', is_forecasted=False, is_paid=True,
    )
    db.session.add(actual)
    db.session.commit()

    for _ in range(2):
        FuelForecastingService.sync_forecasted_transactions(vehicle.id)
        saved = forecasts(vehicle)
        assert len(saved) == 1
        assert saved[0].transaction_date == date(2026, 9, 2)
        assert saved[0].amount == Decimal('-109.10')
        assert saved[0].family_id == vehicle.family_id
    assert db.session.get(Transaction, actual.id).amount == Decimal('-30')


def test_current_status_ignores_future_fills_and_trips(forecast_vehicle):
    vehicle = forecast_vehicle
    today = date.today()
    actual = add_fill(vehicle, today - timedelta(days=2), gallons=3, partial=True)
    add_trip(vehicle, today - timedelta(days=1), 10)
    add_fill(vehicle, today + timedelta(days=1))
    add_trip(vehicle, today + timedelta(days=2), 80)
    status = FuelForecastingService.get_tank_status(vehicle.id)
    assert status['last_fill_date'] == actual.date
    assert status['last_fill_is_partial'] is True
    assert status['gallons_remaining'] == 2.0


def test_fuel_forecasts_count_planned_trips_but_ignore_skipped(forecast_vehicle):
    vehicle = forecast_vehicle
    today = date.today()
    add_fill(vehicle, today - timedelta(days=3))

    def routine_trip(day, miles, status):
        return Trip(
            family_id=vehicle.family_id, vehicle_id=vehicle.id, date=day,
            total_miles=miles, personal_miles=miles, trip_status=status,
        )

    # Unconfirmed past routine trips still burn fuel until a fill confirms them.
    overdue_plan = routine_trip(today - timedelta(days=1), 2, 'planned')
    skipped_past = routine_trip(today - timedelta(days=2), 30, 'skipped')
    planned_future = routine_trip(today + timedelta(days=1), 96, 'planned')
    skipped_future = routine_trip(today + timedelta(days=2), 96, 'skipped')
    db.session.add_all([overdue_plan, skipped_past, planned_future, skipped_future])
    db.session.commit()

    predictions = FuelForecastingService.predict_refills(vehicle.id)
    status = FuelForecastingService.get_tank_status(vehicle.id)

    assert predictions
    assert {p['trigger_trip_id'] for p in predictions} == {planned_future.id}
    assert status['gallons_remaining'] == 9.8
    assert status['miles_since_fill'] == 2


def test_current_status_keeps_exact_threshold_distance(forecast_vehicle):
    today = date.today()
    add_fill(forecast_vehicle, today - timedelta(days=2))
    add_trip(forecast_vehicle, today - timedelta(days=1), 80)
    status = FuelForecastingService.get_tank_status(forecast_vehicle.id)
    assert status['miles_to_refill'] == 15
    assert status['estimated_range_miles'] == 20


def test_partial_fill_mpg_is_derived_full_to_full_even_for_legacy_records(vehicle):
    add_fill(vehicle, date(2026, 1, 1))
    partial = add_fill(vehicle, date(2026, 1, 2), gallons=1, partial=True, mileage=1050)
    full = add_fill(vehicle, date(2026, 1, 3), gallons=9, mileage=1100)
    partial.mpg = 50
    full.mpg = Decimal('5.55555556')
    db.session.commit()
    assert FuelForecastingService.get_average_mpg(vehicle.id) == 10.0
    assert VehicleService.get_vehicle_stats(vehicle.id)['avg_mpg'] == 10
    assert VehicleService.calculate_trip_cost(vehicle.id, 20, date(2026, 1, 4))[2] == 10


def test_fuel_edits_and_deletes_recalculate_downstream_full_interval(vehicle):
    add_fill(vehicle, date(2026, 1, 1))
    partial = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id), 'date': '2026-01-02',
        'price_per_litre': '150', 'mileage': '1050', 'cost': '6.82',
        'gallons': '1', 'is_partial_fill': '1',
    })
    full = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id), 'date': '2026-01-03',
        'price_per_litre': '150', 'mileage': '1100', 'cost': '61.37',
        'gallons': '9', 'is_partial_fill': '0',
    })
    assert partial.mpg == 0
    assert full.mpg == 10
    VehicleService.update_fuel_record(partial.id, {
        'date': '2026-01-02', 'price_per_litre': '150', 'mileage': '1050',
        'cost': '13.64', 'gallons': '2', 'is_partial_fill': '1',
    })
    assert float(full.mpg) == pytest.approx(100 / 11)
    assert full.actual_miles == 50
    VehicleService.delete_fuel_record(partial.id)
    assert float(full.mpg) == pytest.approx(100 / 9)
    assert full.actual_miles == 100
    assert full.actual_cumulative_miles == 100
    assert full.last_fill_date == date(2026, 1, 1)


def test_same_day_full_to_full_mpg_uses_record_order(vehicle):
    add_fill(vehicle, date(2026, 1, 1))
    VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id), 'date': '2026-01-01',
        'price_per_litre': '150', 'mileage': '1050', 'cost': '6.82',
        'gallons': '1', 'is_partial_fill': '1',
    })
    full = VehicleService.create_fuel_record({
        'vehicle_id': str(vehicle.id), 'date': '2026-01-01',
        'price_per_litre': '150', 'mileage': '1100', 'cost': '61.37',
        'gallons': '9', 'is_partial_fill': '0',
    })
    assert full.mpg == 10
    assert full.actual_miles == 50


def test_no_full_to_full_interval_has_no_forecast(vehicle):
    add_fill(vehicle, date(2026, 9, 1), gallons=3, partial=True)
    add_trip(vehicle, date(2026, 9, 2), 80)
    assert FuelForecastingService.get_average_mpg(vehicle.id) is None
    assert FuelForecastingService.predict_refills(vehicle.id) == []
    assert FuelForecastingService.get_tank_status(vehicle.id) is None


@pytest.mark.parametrize('path', [
    '/finance/vehicles/fuel?payday_period=all',
    '/finance/vehicles/trips?payday_period_trip=all',
])
def test_fill_pages_display_derived_legacy_mpg_without_writing_records(
    app, user, vehicle, path,
):
    add_fill(vehicle, date(2026, 1, 1))
    partial = add_fill(vehicle, date(2026, 1, 2), gallons=1, partial=True, mileage=1050)
    full = add_fill(vehicle, date(2026, 1, 3), gallons=9, mileage=1100)
    partial.mpg = 50
    full.mpg = Decimal('5.55555556')
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    response = client.get(path)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert '50.0 mpg' not in body
    assert '5.6 mpg' not in body
    assert '10.0' in body
    assert partial.mpg == 50
    assert full.mpg == Decimal('5.55555556')


@pytest.mark.parametrize('action', ['delete', 'bulk-delete', 'bulk-add', 'vehicle-update'])
def test_edit_routes_refresh_saved_forecasts(app, user, forecast_vehicle, action):
    vehicle = forecast_vehicle
    add_fuel_account(vehicle)
    add_fill(vehicle, date(2026, 9, 1))
    add_trip(vehicle, date(2026, 9, 2), 80)
    trip = add_trip(vehicle, date(2026, 9, 3), 20)
    FuelForecastingService.sync_forecasted_transactions(vehicle.id)
    assert len(forecasts(vehicle)) == 1
    client = app.test_client()
    login_client(client, user.id)
    if action == 'delete':
        response = client.post(f'/finance/vehicles/trip/delete/{trip.id}')
        assert forecasts(vehicle) == []
    elif action == 'bulk-delete':
        response = client.post('/finance/vehicles/trips/bulk-delete', data={'trip_ids': f'[{trip.id}]'})
        assert forecasts(vehicle) == []
    elif action == 'bulk-add':
        response = client.post('/finance/vehicles/trips/bulk-add', data={
            'vehicle_id': vehicle.id, 'start_date': '2026-09-04',
            'end_date': '2026-09-04', 'days': '4', 'miles': '80',
        })
        assert [t.transaction_date for t in forecasts(vehicle)] == [
            date(2026, 9, 3), date(2026, 9, 4),
        ]
    else:
        response = client.post(f'/finance/vehicles/update/{vehicle.id}', data={
            'registration': 'NEW REG', 'tank_size': '20',
            'refuel_threshold_pct': '95', 'fuel_account_id': vehicle.fuel_account_id,
            'is_active': 'on',
        })
        assert family_query(Transaction).filter_by(is_forecasted=True).count() == 0
    assert response.status_code == 302


def test_registration_and_account_change_moves_forecasts_and_invalidates_both_caches(
    app, user, forecast_vehicle, monkeypatch,
):
    vehicle = forecast_vehicle
    old_account, _ = add_fuel_account(vehicle)
    new_account = Account(
        family_id=vehicle.family_id, name='New fuel account', account_type='Current',
        balance=0, is_active=True,
    )
    db.session.add(new_account)
    db.session.commit()
    add_fill(vehicle, date(2026, 9, 1))
    add_trip(vehicle, date(2026, 9, 2), 80)
    add_trip(vehicle, date(2026, 9, 3), 20)
    FuelForecastingService.sync_forecasted_transactions(vehicle.id)
    calls = []
    monkeypatch.setattr(
        MonthlyBalanceService, 'handle_transaction_change',
        staticmethod(lambda account_id, day: calls.append((account_id, day))),
    )
    client = app.test_client()
    login_client(client, user.id)
    response = client.post(f'/finance/vehicles/update/{vehicle.id}', data={
        'registration': 'NEW REG', 'fuel_account_id': new_account.id, 'is_active': 'on',
    })
    assert response.status_code == 302
    saved = forecasts(vehicle)
    assert len(saved) == 1
    assert saved[0].account_id == new_account.id
    assert family_query(Transaction).filter_by(description='Forecasted fuel - FC12 AST').count() == 0
    assert calls == [
        (old_account.id, date(2026, 9, 3)), (new_account.id, date(2026, 9, 3)),
    ]


def test_sync_refreshes_cache_from_earliest_changed_date(forecast_vehicle, monkeypatch):
    vehicle = forecast_vehicle
    account, _ = add_fuel_account(vehicle)
    add_fill(vehicle, date(2026, 9, 1))
    add_trip(vehicle, date(2026, 9, 2), 80)
    add_trip(vehicle, date(2026, 9, 3), 20)
    calls = []
    monkeypatch.setattr(
        MonthlyBalanceService, 'handle_transaction_change',
        staticmethod(lambda account_id, day: calls.append((account_id, day))),
    )
    FuelForecastingService.sync_forecasted_transactions(vehicle.id)
    assert calls == [(account.id, date(2026, 9, 3))]
    calls.clear()
    trip = family_query(Trip).filter_by(vehicle_id=vehicle.id, date=date(2026, 9, 3)).one()
    db.session.delete(trip)
    db.session.commit()
    FuelForecastingService.sync_forecasted_transactions(vehicle.id)
    assert calls == [(account.id, date(2026, 9, 3))]
