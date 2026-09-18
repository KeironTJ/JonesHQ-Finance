from flask import render_template, request, redirect, url_for, flash, jsonify
import logging
from . import vehicles_bp
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.accounts import Account
from services.vehicle_service import VehicleService
from services.fuel_forecasting_service import FuelForecastingService
from extensions import db
from datetime import datetime, date, timedelta
from decimal import Decimal
from services.payday_service import PaydayService
from sqlalchemy.orm import joinedload
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id

log = logging.getLogger(__name__)


@vehicles_bp.route('/vehicles')
def index():
    """Vehicle overview page (also hosts Manage Fleet tab)"""
    active_vehicles = family_query(Vehicle).filter_by(is_active=True).order_by(Vehicle.name).all()
    all_vehicles = family_query(Vehicle).order_by(Vehicle.is_active.desc(), Vehicle.name).all()
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()

    # active_tab: 'fleet' (default) or 'manage'
    active_tab = request.args.get('tab', 'fleet')

    # Get stats and tank status for each active vehicle
    vehicle_stats = {}
    tank_statuses = {}
    next_predicted_refills = {}
    for vehicle in active_vehicles:
        vehicle_stats[vehicle.id] = VehicleService.get_vehicle_stats(vehicle.id)
        tank_statuses[vehicle.id] = FuelForecastingService.get_tank_status(vehicle.id)
        predictions = FuelForecastingService.predict_refills(vehicle.id)
        from datetime import date as _date
        future = [p for p in predictions if p['date'] >= _date.today()]
        next_predicted_refills[vehicle.id] = future[0] if future else None

    # Last fuel fill per vehicle — single batched query to pre-fill the Add Fuel modal
    _subq = (
        family_query(FuelRecord)
        .with_entities(FuelRecord.vehicle_id, db.func.max(FuelRecord.id).label('last_id'))
        .group_by(FuelRecord.vehicle_id)
        .subquery()
    )
    _last_fills = family_query(FuelRecord).join(_subq, FuelRecord.id == _subq.c.last_id).all()
    last_fill_by_vehicle = {
        r.vehicle_id: {
            'price_per_litre': float(r.price_per_litre) if r.price_per_litre else 0,
            'mileage': r.mileage or 0,
        }
        for r in _last_fills
    }

    return render_template(
        'vehicles/index.html',
        vehicles=active_vehicles,
        all_vehicles=all_vehicles,
        accounts=accounts,
        vehicle_stats=vehicle_stats,
        tank_statuses=tank_statuses,
        next_predicted_refills=next_predicted_refills,
        last_fill_by_vehicle=last_fill_by_vehicle,
        active_tab=active_tab,
        today=date.today(),
    )


@vehicles_bp.route('/vehicles/fuel')
def fuel():
    """Fuel log page (standalone)"""
    vehicles = family_query(Vehicle).filter_by(is_active=True).order_by(Vehicle.name).all()
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()

    # Payday filter for fuel
    selected_payday_period = request.args.get('payday_period')
    
    # If no period specified in URL, default to current payday period
    if selected_payday_period is None:
        today = date.today()
        selected_payday_period = PaydayService.get_period_for_date(today)
    elif selected_payday_period == 'all' or selected_payday_period == '':
        selected_payday_period = ''

    # Get date range of fuel records to determine relevant periods
    min_date_result = family_query(FuelRecord).with_entities(db.func.min(FuelRecord.date)).scalar()
    max_date_result = family_query(FuelRecord).with_entities(db.func.max(FuelRecord.date)).scalar()
    
    if min_date_result and max_date_result:
        # Calculate number of months between min and max dates
        months_diff = (max_date_result.year - min_date_result.year) * 12 + (max_date_result.month - min_date_result.month) + 2
        payday_periods = PaydayService.get_recent_periods(
            num_periods=months_diff,
            include_future=False,
            start_year=min_date_result.year,
            start_month=min_date_result.month
        )
    else:
        payday_periods = []

    # Vehicle filter for fuel
    selected_vehicle_id = request.args.get('vehicle_id')

    # Get fuel records
    fuel_query = family_query(FuelRecord)
    if selected_payday_period:
        try:
            year, month = map(int, selected_payday_period.split('-'))
            start_date, end_date, _ = PaydayService.get_payday_period(year, month)
            fuel_query = fuel_query.filter(FuelRecord.date >= start_date, FuelRecord.date <= end_date)
        except Exception:
            pass
    if selected_vehicle_id:
        try:
            fuel_query = fuel_query.filter(FuelRecord.vehicle_id == int(selected_vehicle_id))
        except Exception:
            pass
    fuel_records = fuel_query.order_by(FuelRecord.date.desc()).all()

    # Last fuel fill per vehicle — single batched query to pre-fill the Add Fuel modal
    _subq = (
        family_query(FuelRecord)
        .with_entities(FuelRecord.vehicle_id, db.func.max(FuelRecord.id).label('last_id'))
        .group_by(FuelRecord.vehicle_id)
        .subquery()
    )
    _last_fills = family_query(FuelRecord).join(_subq, FuelRecord.id == _subq.c.last_id).all()
    last_fill_by_vehicle = {
        r.vehicle_id: {
            'price_per_litre': float(r.price_per_litre) if r.price_per_litre else 0,
            'mileage': r.mileage or 0,
        }
        for r in _last_fills
    }

    return render_template(
        'vehicles/fuel_log.html',
        fuel_records=fuel_records,
        vehicles=vehicles,
        accounts=accounts,
        payday_periods=payday_periods,
        selected_payday_period=selected_payday_period,
        selected_vehicle_id=selected_vehicle_id,
        last_fill_by_vehicle=last_fill_by_vehicle
    )


@vehicles_bp.route('/vehicles/trips')
def trips():
    """Trip log page (standalone)"""
    vehicles = family_query(Vehicle).filter_by(is_active=True).order_by(Vehicle.name).all()

    # Trip-specific payday filter
    selected_payday_period_trip = request.args.get('payday_period_trip')
    
    # If no period specified in URL, default to current payday period
    if selected_payday_period_trip is None:
        today = date.today()
        selected_payday_period_trip = PaydayService.get_period_for_date(today)
    elif selected_payday_period_trip == 'all' or selected_payday_period_trip == '':
        selected_payday_period_trip = ''

    # Get date range of trip records to determine relevant periods
    min_date_result = family_query(Trip).with_entities(db.func.min(Trip.date)).scalar()
    max_date_result = family_query(Trip).with_entities(db.func.max(Trip.date)).scalar()
    
    if min_date_result and max_date_result:
        # Calculate number of months between min and max dates
        months_diff = (max_date_result.year - min_date_result.year) * 12 + (max_date_result.month - min_date_result.month) + 2
        payday_periods = PaydayService.get_recent_periods(
            num_periods=months_diff,
            include_future=False,
            start_year=min_date_result.year,
            start_month=min_date_result.month
        )
    else:
        payday_periods = []

    # Trip vehicle filter
    selected_vehicle_id_trip = request.args.get('vehicle_id_trip')

    # Get trip records
    trip_start_date = None
    trip_end_date = None
    trip_query = family_query(Trip).options(joinedload(Trip.fuel_record))
    if selected_payday_period_trip:
        try:
            year, month = map(int, selected_payday_period_trip.split('-'))
            trip_start_date, trip_end_date, _ = PaydayService.get_payday_period(year, month)
            trip_query = trip_query.filter(Trip.date >= trip_start_date, Trip.date <= trip_end_date)
        except Exception:
            pass
    if selected_vehicle_id_trip:
        try:
            trip_query = trip_query.filter(Trip.vehicle_id == int(selected_vehicle_id_trip))
        except Exception:
            pass
    trips = trip_query.order_by(Trip.date.desc(), Trip.id.desc()).all()
    
    # Get all fuel records per vehicle for the timeline.
    # Scoped to the active date range where possible to avoid loading full history.
    all_vehicle_fills = {}
    for vehicle in vehicles:
        q = family_query(FuelRecord).filter_by(vehicle_id=vehicle.id)
        if trip_start_date and trip_end_date:
            q = q.filter(FuelRecord.date >= trip_start_date, FuelRecord.date <= trip_end_date)
        all_vehicle_fills[vehicle.id] = q.order_by(FuelRecord.date.asc()).all()

    # Get forecasted fuel transactions (keyed by vehicle id → transaction_date → tx)
    from models.categories import Category
    from models.transactions import Transaction
    from models.expenses import Expense
    fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
    forecasted_transactions = {}
    if fuel_category:
        forecasted_fuel = family_query(Transaction).filter(
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id
        ).all()
        for trans in forecasted_fuel:
            for vehicle in vehicles:
                if vehicle.registration in trans.description:
                    if vehicle.id not in forecasted_transactions:
                        forecasted_transactions[vehicle.id] = {}
                    forecasted_transactions[vehicle.id][trans.transaction_date] = trans
                    break

    # Get fuel expenses keyed by trip ID via sentinel description match
    fuel_expenses_all = family_query(Expense).filter_by(expense_type='Fuel').all()
    fuel_expenses_by_trip = {}
    for exp in fuel_expenses_all:
        sentinel = f"Expense #{exp.id}: {exp.description}"
        for trip in trips:
            if trip.journey_description == sentinel:
                fuel_expenses_by_trip[trip.id] = exp
                break

    # Tank levels per trip (estimated % at end of each trip)
    trip_tank_levels = {}
    if selected_vehicle_id_trip:
        try:
            trip_tank_levels = FuelForecastingService.get_trip_tank_levels(int(selected_vehicle_id_trip))
        except Exception as e:
            log.warning('get_trip_tank_levels failed for vehicle %s: %s', selected_vehicle_id_trip, e)
    else:
        for vehicle in vehicles:
            try:
                trip_tank_levels.update(FuelForecastingService.get_trip_tank_levels(vehicle.id))
            except Exception as e:
                log.warning('get_trip_tank_levels failed for vehicle %s: %s', vehicle.id, e)

    # ── Build combined timeline events ──────────────────────────────────────
    vid_filter = int(selected_vehicle_id_trip) if selected_vehicle_id_trip else None

    # Fuel fills within the same date/vehicle range for the timeline
    fills_for_timeline = []
    for vehicle in vehicles:
        if vid_filter and vehicle.id != vid_filter:
            continue
        for fill in all_vehicle_fills.get(vehicle.id, []):
            if trip_start_date and trip_end_date:
                if not (trip_start_date <= fill.date <= trip_end_date):
                    continue
            fills_for_timeline.append(fill)

    vehicles_by_id = {v.id: v for v in vehicles}
    # For 0-mile trips that get no entry in trip_tank_levels, carry forward
    # the nearest previous trip's tank level so the bar still renders.
    _sorted_for_fallback = sorted(trips, key=lambda t: (t.date, t.id))
    _last_known_tank = None
    _tank_fallback = {}  # trip_id → fallback pct
    for _t in _sorted_for_fallback:
        _pct = trip_tank_levels.get(_t.id)
        if _pct is not None:
            _last_known_tank = _pct
        elif _last_known_tank is not None:
            _tank_fallback[_t.id] = _last_known_tank

    events = []
    seen_checkbox = set()

    for trip in sorted(trips, key=lambda t: (t.date, t.id), reverse=True):
        _tank = trip_tank_levels.get(trip.id)
        if _tank is None:
            _tank = _tank_fallback.get(trip.id)
        base = dict(
            date=trip.date,
            trip=trip,
            tank_pct=_tank,
            fuel_expense=fuel_expenses_by_trip.get(trip.id),
        )
        first_row = trip.id not in seen_checkbox
        seen_checkbox.add(trip.id)
        if trip.personal_miles:
            events.append({**base, 'type': 'personal', 'miles': trip.personal_miles,
                            'show_checkbox': first_row, 'is_continuation': False})
            first_row = False
        if trip.business_miles:
            events.append({**base, 'type': 'business', 'miles': trip.business_miles,
                            'show_checkbox': first_row, 'is_continuation': False})
            first_row = False
        if not trip.personal_miles and not trip.business_miles:
            events.append({**base, 'type': 'personal', 'miles': 0,
                           'show_checkbox': True, 'is_continuation': False})

    for fill in fills_for_timeline:
        # Calculate tank % after this fill:
        # full fill → 100 %; partial → gallons added / tank_size × 100 (capped at 100)
        fill_tank_pct = None
        try:
            tank_size = float(fill.vehicle.tank_size) if fill.vehicle and fill.vehicle.tank_size else None
            if tank_size and tank_size > 0:
                if not fill.is_partial_fill:
                    fill_tank_pct = 100.0
                elif fill.gallons:
                    fill_tank_pct = min(100.0, float(fill.gallons) / tank_size * 100)
        except Exception as e:
            log.warning('fill tank_pct calc failed for fill %s: %s', fill.id, e)
        events.append({
            'type': 'fuel',
            'date': fill.date,
            'fill': fill,
            'tank_pct': fill_tank_pct,
            'show_checkbox': False,
            'is_continuation': False,
        })

    for vid, date_map in forecasted_transactions.items():
        if vid_filter and vid != vid_filter:
            continue
        for tx_date, tx in date_map.items():
            if trip_start_date and trip_end_date:
                if not (trip_start_date <= tx_date <= trip_end_date):
                    continue
            # Predicted fills always top up to full → 100 % (if vehicle has tank_size)
            forecast_tank_pct = None
            _fv = vehicles_by_id.get(vid)
            if _fv and getattr(_fv, 'tank_size', None):
                forecast_tank_pct = 100.0
            events.append({
                'type': 'forecasted',
                'date': tx_date,
                'tx': tx,
                'vehicle': _fv,
                'tank_pct': forecast_tank_pct,
                'show_checkbox': False,
                'is_continuation': False,
            })

    _type_order = {'fuel': 0, 'forecasted': 0, 'personal': 1, 'business': 1}
    events.sort(key=lambda e: (e['date'], _type_order.get(e['type'], 1)), reverse=True)

    # Mark business rows that immediately follow their personal counterpart
    prev_trip_id = None
    for ev in events:
        t = ev.get('trip')
        if ev['type'] == 'business' and t and t.id == prev_trip_id:
            ev['is_continuation'] = True
        prev_trip_id = t.id if t else None
    # ────────────────────────────────────────────────────────────────────────

    return render_template(
        'vehicles/trip_log.html',
        events=events,
        trips=trips,
        vehicles=vehicles,
        payday_periods=payday_periods,
        selected_payday_period_trip=selected_payday_period_trip,
        selected_vehicle_id_trip=selected_vehicle_id_trip,
        today=date.today()
    )


@vehicles_bp.route('/vehicles/manage')
def manage():
    """Redirect to combined overview/manage page"""
    return redirect(url_for('vehicles.index', tab='manage'))


# ===== VEHICLE MANAGEMENT =====

@vehicles_bp.route('/vehicles/add', methods=['POST'])
def add_vehicle():
    """Add a new vehicle"""
    try:
        vehicle = VehicleService.create_vehicle(request.form)
        name = vehicle.name
        registration = vehicle.registration
        
        flash(f'Vehicle {name} ({registration}) added successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding vehicle: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/update/<int:vehicle_id>', methods=['POST'])
def update_vehicle(vehicle_id):
    """Update vehicle details"""
    try:
        vehicle = VehicleService.update_vehicle(vehicle_id, request.form)
        flash(f'Vehicle {vehicle.name} updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating vehicle: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/<int:vehicle_id>/refresh-forecasts', methods=['POST'])
def refresh_forecasts(vehicle_id):
    """Manually refresh forecasted fuel transactions for a vehicle"""
    try:
        vehicle = family_get_or_404(Vehicle, vehicle_id)
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        # Update monthly balance cache for fuel account
        from services.monthly_balance_service import MonthlyBalanceService
        from datetime import date
        if vehicle.fuel_account_id:
            MonthlyBalanceService.handle_transaction_change(
                vehicle.fuel_account_id,
                date.today()
            )
        
        flash(f'Forecasted fuel transactions refreshed for {vehicle.name}', 'success')
    except Exception as e:
        flash(f'Error refreshing forecasts: {str(e)}', 'danger')
    
    # Redirect back to the page they came from
    return redirect(request.referrer or url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/refresh-all-forecasts', methods=['POST'])
def refresh_all_forecasts():
    """Manually refresh forecasted fuel transactions for all vehicles"""
    try:
        # Get all vehicle data BEFORE calling any services that commit
        vehicles = family_query(Vehicle).filter_by(is_active=True).all()
        vehicle_data = [(v.id, v.name) for v in vehicles]
        
        refreshed_count = 0
        
        for vehicle_id, vehicle_name in vehicle_data:
            try:
                FuelForecastingService.sync_forecasted_transactions(vehicle_id)
                refreshed_count += 1
            except Exception as e:
                db.session.rollback()
                flash(f'Error refreshing forecasts for {vehicle_name}: {str(e)}', 'warning')
        
        flash(f'Forecasted fuel transactions refreshed for {refreshed_count} vehicle(s)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error refreshing forecasts: {str(e)}', 'danger')
    
    # Redirect back to the page they came from
    return redirect(request.referrer or url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/delete/<int:vehicle_id>', methods=['POST'])
def delete_vehicle(vehicle_id):
    """Delete a vehicle"""
    try:
        name = VehicleService.delete_vehicle(vehicle_id)
        
        flash(f'Vehicle {name} deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting vehicle: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


# ===== FUEL LOG =====

@vehicles_bp.route('/vehicles/fuel/add', methods=['POST'])
def add_fuel():
    """Add a fuel record"""
    try:
        fuel_record = VehicleService.create_fuel_record(request.form)
        vehicle_id = fuel_record.vehicle_id
        
        # Link to transaction (replaces forecasted or creates new)
        FuelForecastingService.link_fuel_record_to_transaction(fuel_record.id)
        
        db.session.commit()
        
        # Update cache after commit (manually since we disabled the event handler)
        from services.monthly_balance_service import MonthlyBalanceService
        from models.transactions import Transaction
        if fuel_record.linked_transaction_id:
            txn = family_get(Transaction, fuel_record.linked_transaction_id)
            if txn and txn.account_id:
                MonthlyBalanceService.handle_transaction_change(txn.account_id, txn.transaction_date)
        
        # Regenerate future fuel forecasts
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        flash(
            f'Fuel record added: £{fuel_record.cost:.2f}, '
            f'{fuel_record.mpg:.1f} MPG',
            'success',
        )
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding fuel record: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/fuel/update/<int:fuel_id>', methods=['POST'])
def update_fuel(fuel_id):
    """Update a fuel record"""
    try:
        fuel_record = VehicleService.update_fuel_record(fuel_id, request.form)
        
        # Regenerate future fuel forecasts
        FuelForecastingService.sync_forecasted_transactions(fuel_record.vehicle_id)
        
        flash('Fuel record updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating fuel record: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/fuel/delete/<int:fuel_id>', methods=['POST'])
def delete_fuel(fuel_id):
    """Delete a fuel record"""
    try:
        vehicle_id = VehicleService.delete_fuel_record(fuel_id)
        
        # Regenerate future fuel forecasts
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        flash('Fuel record deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting fuel record: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


# ===== TRIP LOG =====

@vehicles_bp.route('/vehicles/trip/add', methods=['POST'])
def add_trip():
    """Add a trip record"""
    try:
        trip = VehicleService.create_trip(request.form)
        vehicle_id = trip.vehicle_id
        
        # Trigger fuel forecasting for this vehicle
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        flash(f'Trip added: {trip.total_miles} miles, £{trip.trip_cost:.2f}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding trip: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('vehicles.trips'))


@vehicles_bp.route('/vehicles/trip/update/<int:trip_id>', methods=['POST'])
def update_trip(trip_id):
    """Update a trip record"""
    try:
        trip = VehicleService.update_trip(trip_id, request.form)
        
        # Trigger fuel forecasting for this vehicle
        FuelForecastingService.sync_forecasted_transactions(trip.vehicle_id)
        
        flash('Trip updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating trip: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('vehicles.trips'))


@vehicles_bp.route('/vehicles/trip/delete/<int:trip_id>', methods=['POST'])
def delete_trip(trip_id):
    """Delete a trip record"""
    try:
        VehicleService.delete_trip(trip_id)
        
        flash('Trip deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting trip: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('vehicles.trips'))


@vehicles_bp.route('/vehicles/trips/bulk-delete', methods=['POST'])
def bulk_delete_trips():
    """Bulk delete trip records"""
    try:
        import json
        trip_ids_json = request.form.get('trip_ids')
        trip_ids = json.loads(trip_ids_json) if trip_ids_json else []
        
        if not trip_ids:
            flash('No trips selected for deletion', 'warning')
            return redirect(request.referrer or url_for('vehicles.trips'))
        
        # Delete all selected trips
        deleted_count = 0
        for trip_id in trip_ids:
            trip = family_get(Trip, int(trip_id))
            if trip:
                db.session.delete(trip)
                deleted_count += 1
        
        db.session.commit()
        flash(f'Successfully deleted {deleted_count} trip(s)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting trips: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('vehicles.trips'))


@vehicles_bp.route('/vehicles/trips/bulk-add', methods=['POST'])
def bulk_add_trips():
    """Bulk add recurring trips based on date range and selected days of week"""
    try:
        if not request.form.get('vehicle_id') or not request.form.get('start_date') or not request.form.get('end_date') or not request.form.getlist('days'):
            flash('Please fill in all required fields and select at least one day', 'danger')
            return redirect(request.referrer or url_for('vehicles.trips'))
        created = VehicleService.bulk_create_trips(request.form)
        created_count = len(created)
        flash(f'Successfully created {created_count} trip(s)', 'success')
    except ValueError as ve:
        db.session.rollback()
        flash(f'Invalid input: {str(ve)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating trips: {str(e)}', 'danger')
    
    return redirect(request.referrer or url_for('vehicles.trips'))
