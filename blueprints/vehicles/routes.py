from flask import render_template, request, redirect, url_for, flash, jsonify
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


@vehicles_bp.route('/vehicles')
def index():
    """Vehicle overview page"""
    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.name).all()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

    # Get stats for each vehicle
    vehicle_stats = {}
    for vehicle in vehicles:
        vehicle_stats[vehicle.id] = VehicleService.get_vehicle_stats(vehicle.id)

    return render_template(
        'vehicles/index.html',
        vehicles=vehicles,
        accounts=accounts,
        vehicle_stats=vehicle_stats
    )


@vehicles_bp.route('/vehicles/fuel')
def fuel():
    """Fuel log page (standalone)"""
    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.name).all()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

    # Payday filter for fuel
    selected_payday_period = request.args.get('payday_period')
    
    # If no period specified in URL, default to current payday period
    if selected_payday_period is None:
        today = date.today()
        selected_payday_period = PaydayService.get_period_for_date(today)
    elif selected_payday_period == 'all' or selected_payday_period == '':
        selected_payday_period = ''

    # Get date range of fuel records to determine relevant periods
    min_date_result = db.session.query(db.func.min(FuelRecord.date)).scalar()
    max_date_result = db.session.query(db.func.max(FuelRecord.date)).scalar()
    
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
    fuel_query = FuelRecord.query
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

    return render_template(
        'vehicles/fuel_log.html',
        fuel_records=fuel_records,
        vehicles=vehicles,
        accounts=accounts,
        payday_periods=payday_periods,
        selected_payday_period=selected_payday_period,
        selected_vehicle_id=selected_vehicle_id
    )


@vehicles_bp.route('/vehicles/trips')
def trips():
    """Trip log page (standalone)"""
    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.name).all()

    # Trip-specific payday filter
    selected_payday_period_trip = request.args.get('payday_period_trip')
    
    # If no period specified in URL, default to current payday period
    if selected_payday_period_trip is None:
        today = date.today()
        selected_payday_period_trip = PaydayService.get_period_for_date(today)
    elif selected_payday_period_trip == 'all' or selected_payday_period_trip == '':
        selected_payday_period_trip = ''

    # Get date range of trip records to determine relevant periods
    min_date_result = db.session.query(db.func.min(Trip.date)).scalar()
    max_date_result = db.session.query(db.func.max(Trip.date)).scalar()
    
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
    trip_query = Trip.query.options(joinedload(Trip.fuel_record))
    if selected_payday_period_trip:
        try:
            year, month = map(int, selected_payday_period_trip.split('-'))
            start_date, end_date, _ = PaydayService.get_payday_period(year, month)
            trip_query = trip_query.filter(Trip.date >= start_date, Trip.date <= end_date)
        except Exception:
            pass
    if selected_vehicle_id_trip:
        try:
            trip_query = trip_query.filter(Trip.vehicle_id == int(selected_vehicle_id_trip))
        except Exception:
            pass
    trips = trip_query.order_by(Trip.date.desc()).all()
    
    # Get all fuel records to check for linked transactions
    fuel_records_dict = {}
    for vehicle in vehicles:
        fuel_records = FuelRecord.query.filter_by(vehicle_id=vehicle.id).all()
        fuel_records_dict[vehicle.id] = {f.date: f for f in fuel_records}
    
    # Get forecasted fuel transactions
    from models.categories import Category
    from models.transactions import Transaction
    from models.expenses import Expense
    fuel_category = Category.query.filter_by(name='Transportation - Fuel').first()
    forecasted_transactions = {}
    if fuel_category:
        forecasted_fuel = Transaction.query.filter(
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id
        ).all()
        # Group by vehicle registration extracted from description
        for trans in forecasted_fuel:
            # Description format: "Forecasted fuel - ABC123" or similar
            for vehicle in vehicles:
                if vehicle.registration in trans.description:
                    if vehicle.id not in forecasted_transactions:
                        forecasted_transactions[vehicle.id] = {}
                    forecasted_transactions[vehicle.id][trans.transaction_date] = trans
                    break
    
    # Get fuel expenses to show linked entries
    fuel_expenses = Expense.query.filter_by(expense_type='Fuel').all()
    fuel_expenses_dict = {}
    for vehicle in vehicles:
        vehicle_expenses = [e for e in fuel_expenses if e.vehicle_registration == vehicle.registration]
        fuel_expenses_dict[vehicle.id] = {e.date: e for e in vehicle_expenses}

    return render_template(
        'vehicles/trip_log.html',
        trips=trips,
        vehicles=vehicles,
        payday_periods=payday_periods,
        selected_payday_period_trip=selected_payday_period_trip,
        selected_vehicle_id_trip=selected_vehicle_id_trip,
        fuel_records_dict=fuel_records_dict,
        forecasted_transactions=forecasted_transactions,
        fuel_expenses_dict=fuel_expenses_dict,
        today=date.today()
    )


@vehicles_bp.route('/vehicles/manage')
def manage():
    """Manage vehicles page (standalone)"""
    vehicles = Vehicle.query.order_by(Vehicle.is_active.desc(), Vehicle.name).all()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

    return render_template(
        'vehicles/manage_vehicles.html',
        vehicles=vehicles,
        accounts=accounts
    )


# ===== VEHICLE MANAGEMENT =====

@vehicles_bp.route('/vehicles/add', methods=['POST'])
def add_vehicle():
    """Add a new vehicle"""
    try:
        name = request.form.get('name')
        make = request.form.get('make')
        model = request.form.get('model')
        registration = request.form.get('registration').upper()
        tank_size = request.form.get('tank_size')
        fuel_type = request.form.get('fuel_type')
        year = request.form.get('year')
        starting_mileage = request.form.get('starting_mileage')
        fuel_account_id = request.form.get('fuel_account_id')
        
        vehicle = Vehicle(
            name=name,
            make=make,
            model=model,
            registration=registration,
            tank_size=Decimal(tank_size) if tank_size else None,
            fuel_type=fuel_type,
            year=int(year) if year else None,
            starting_mileage=int(starting_mileage) if starting_mileage else None,
            fuel_account_id=int(fuel_account_id) if fuel_account_id else None,
            is_active=True
        )
        db.session.add(vehicle)
        db.session.commit()
        
        flash(f'Vehicle {name} ({registration}) added successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding vehicle: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/update/<int:vehicle_id>', methods=['POST'])
def update_vehicle(vehicle_id):
    """Update vehicle details"""
    try:
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        
        vehicle.name = request.form.get('name', vehicle.name)
        vehicle.make = request.form.get('make', vehicle.make)
        vehicle.model = request.form.get('model', vehicle.model)
        vehicle.registration = request.form.get('registration', vehicle.registration).upper()
        vehicle.fuel_type = request.form.get('fuel_type', vehicle.fuel_type)
        vehicle.is_active = request.form.get('is_active') == 'on'
        
        tank_size = request.form.get('tank_size')
        if tank_size:
            vehicle.tank_size = Decimal(tank_size)
        
        year = request.form.get('year')
        if year:
            vehicle.year = int(year)
        
        fuel_account_id = request.form.get('fuel_account_id')
        vehicle.fuel_account_id = int(fuel_account_id) if fuel_account_id else None
        
        db.session.commit()
        flash(f'Vehicle {vehicle.name} updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating vehicle: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/<int:vehicle_id>/refresh-forecasts', methods=['POST'])
def refresh_forecasts(vehicle_id):
    """Manually refresh forecasted fuel transactions for a vehicle"""
    try:
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        # Update monthly balance cache for fuel account
        from services.monthly_balance_service import MonthlyBalanceService
        from datetime import date
        if vehicle.default_fuel_account_id:
            MonthlyBalanceService.handle_transaction_change(
                vehicle.default_fuel_account_id,
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
        vehicles = Vehicle.query.filter_by(is_active=True).all()
        vehicle_data = [(v.id, v.name) for v in vehicles]
        
        refreshed_count = 0
        
        for vehicle_id, vehicle_name in vehicle_data:
            try:
                FuelForecastingService.sync_forecasted_transactions(vehicle_id)
                # Clear the session after each commit to avoid 'committed' state errors
                db.session.remove()
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
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        name = vehicle.name
        
        db.session.delete(vehicle)
        db.session.commit()
        
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
        vehicle_id = int(request.form.get('vehicle_id'))
        fuel_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        price_per_litre = Decimal(request.form.get('price_per_litre'))
        mileage = int(request.form.get('mileage'))
        cost = Decimal(request.form.get('cost'))
        gallons = Decimal(request.form.get('gallons'))
        
        # Calculate metrics
        actual_miles, mpg, price_per_mile, last_fill_date, cumulative_miles = VehicleService.calculate_fuel_metrics(
            vehicle_id, mileage, gallons, cost, fuel_date
        )
        
        fuel_record = FuelRecord(
            vehicle_id=vehicle_id,
            date=fuel_date,
            price_per_litre=price_per_litre,
            mileage=mileage,
            cost=cost,
            gallons=gallons,
            actual_miles=actual_miles,
            actual_cumulative_miles=cumulative_miles,
            mpg=mpg,
            price_per_mile=price_per_mile,
            last_fill_date=last_fill_date
        )
        db.session.add(fuel_record)
        db.session.flush()  # Flush to get the ID
        
        # Link to transaction (replaces forecasted or creates new)
        FuelForecastingService.link_fuel_record_to_transaction(fuel_record.id)
        
        db.session.commit()
        
        # Update cache after commit (manually since we disabled the event handler)
        from services.monthly_balance_service import MonthlyBalanceService
        from models.transactions import Transaction
        if fuel_record.transaction_id:
            txn = Transaction.query.get(fuel_record.transaction_id)
            if txn and txn.account_id:
                MonthlyBalanceService.handle_transaction_change(txn.account_id, txn.transaction_date)
        
        # Regenerate future fuel forecasts
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        flash(f'Fuel record added: £{cost:.2f}, {mpg:.1f} MPG', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding fuel record: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/fuel/update/<int:fuel_id>', methods=['POST'])
def update_fuel(fuel_id):
    """Update a fuel record"""
    try:
        fuel_record = FuelRecord.query.get_or_404(fuel_id)
        
        fuel_record.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        fuel_record.price_per_litre = Decimal(request.form.get('price_per_litre'))
        fuel_record.mileage = int(request.form.get('mileage'))
        fuel_record.cost = Decimal(request.form.get('cost'))
        fuel_record.gallons = Decimal(request.form.get('gallons'))
        
        # Recalculate metrics
        actual_miles, mpg, price_per_mile, last_fill_date, cumulative_miles = VehicleService.calculate_fuel_metrics(
            fuel_record.vehicle_id, fuel_record.mileage, fuel_record.gallons, fuel_record.cost, fuel_record.date
        )
        
        fuel_record.actual_miles = actual_miles
        fuel_record.mpg = mpg
        fuel_record.price_per_mile = price_per_mile
        fuel_record.last_fill_date = last_fill_date
        fuel_record.actual_cumulative_miles = cumulative_miles
        
        db.session.commit()
        
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
        fuel_record = FuelRecord.query.get_or_404(fuel_id)
        vehicle_id = fuel_record.vehicle_id  # Store before deletion
        db.session.delete(fuel_record)
        db.session.commit()
        
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
        vehicle_id = int(request.form.get('vehicle_id'))
        trip_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        personal_miles = int(request.form.get('personal_miles', 0))
        business_miles = int(request.form.get('business_miles', 0))
        total_miles = personal_miles + business_miles
        journey_description = request.form.get('journey_description', '')
        school_holidays = request.form.get('school_holidays', '')
        
        # Calculate fuel cost
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(vehicle_id, total_miles, trip_date)
        
        # Get latest fuel record for reference
        latest_fuel = VehicleService.get_latest_fuel_record(vehicle_id)
        vehicle_last_fill = latest_fuel.date if latest_fuel else None
        
        # Get cumulative miles from previous trip
        previous_trip = Trip.query.filter(
            Trip.vehicle_id == vehicle_id,
            Trip.date < trip_date
        ).order_by(Trip.date.desc()).first()
        
        cumulative_total_miles = (previous_trip.cumulative_total_miles or 0) + total_miles if previous_trip else total_miles
        
        # Calculate cumulative gallons
        previous_cumulative_gallons = previous_trip.cumulative_gallons or Decimal('0') if previous_trip else Decimal('0')
        cumulative_gallons = previous_cumulative_gallons + gallons_used
        
        trip = Trip(
            vehicle_id=vehicle_id,
            date=trip_date,
            month=f"{trip_date.year}-{trip_date.month:02d}",
            week=f"{trip_date.isocalendar()[1]:02d}-{trip_date.year}",
            day_name=trip_date.strftime('%A'),
            personal_miles=personal_miles,
            business_miles=business_miles,
            total_miles=total_miles,
            cumulative_total_miles=cumulative_total_miles,
            journey_description=journey_description,
            school_holidays=school_holidays,
            approx_mpg=approx_mpg,
            gallons_used=gallons_used,
            cumulative_gallons=cumulative_gallons,
            trip_cost=trip_cost,
            fuel_cost=Decimal('0'),  # Only set when fuel is purchased
            vehicle_last_fill=vehicle_last_fill
        )
        db.session.add(trip)
        db.session.commit()
        
        # Trigger fuel forecasting for this vehicle
        FuelForecastingService.sync_forecasted_transactions(vehicle_id)
        
        flash(f'Trip added: {total_miles} miles, £{trip_cost:.2f}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding trip: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/trip/update/<int:trip_id>', methods=['POST'])
def update_trip(trip_id):
    """Update a trip record"""
    try:
        trip = Trip.query.get_or_404(trip_id)
        
        trip.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        trip.personal_miles = int(request.form.get('personal_miles', 0))
        trip.business_miles = int(request.form.get('business_miles', 0))
        trip.total_miles = trip.personal_miles + trip.business_miles
        trip.journey_description = request.form.get('journey_description', '')
        trip.school_holidays = request.form.get('school_holidays', '')
        
        # Recalculate costs
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(trip.vehicle_id, trip.total_miles, trip.date)
        trip.trip_cost = trip_cost
        trip.gallons_used = gallons_used
        trip.approx_mpg = approx_mpg
        
        db.session.commit()
        
        # Trigger fuel forecasting for this vehicle
        FuelForecastingService.sync_forecasted_transactions(trip.vehicle_id)
        
        flash('Trip updated successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating trip: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/trip/delete/<int:trip_id>', methods=['POST'])
def delete_trip(trip_id):
    """Delete a trip record"""
    try:
        trip = Trip.query.get_or_404(trip_id)
        db.session.delete(trip)
        db.session.commit()
        
        flash('Trip deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting trip: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.index'))


@vehicles_bp.route('/vehicles/trips/bulk-delete', methods=['POST'])
def bulk_delete_trips():
    """Bulk delete trip records"""
    try:
        import json
        trip_ids_json = request.form.get('trip_ids')
        trip_ids = json.loads(trip_ids_json) if trip_ids_json else []
        
        if not trip_ids:
            flash('No trips selected for deletion', 'warning')
            return redirect(url_for('vehicles.trips'))
        
        # Delete all selected trips
        deleted_count = 0
        for trip_id in trip_ids:
            trip = Trip.query.get(int(trip_id))
            if trip:
                db.session.delete(trip)
                deleted_count += 1
        
        db.session.commit()
        flash(f'Successfully deleted {deleted_count} trip(s)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting trips: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.trips'))


@vehicles_bp.route('/vehicles/trips/bulk-add', methods=['POST'])
def bulk_add_trips():
    """Bulk add recurring trips based on date range and selected days of week"""
    try:
        vehicle_id = request.form.get('vehicle_id')
        journey_description = request.form.get('journey_description', '')
        personal_miles = Decimal(request.form.get('personal_miles', 0))
        business_miles = Decimal(request.form.get('business_miles', 0))
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        selected_days = request.form.getlist('days')  # List of weekday integers (0=Monday, 6=Sunday)
        
        # Validate inputs
        if not vehicle_id or not start_date_str or not end_date_str or not selected_days:
            flash('Please fill in all required fields and select at least one day', 'danger')
            return redirect(url_for('vehicles.trips'))
        
        # Convert to integers
        selected_days = [int(day) for day in selected_days]
        
        # Parse dates
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if start_date > end_date:
            flash('Start date must be before or equal to end date', 'danger')
            return redirect(url_for('vehicles.trips'))
        
        # Create trips for selected days in the date range
        created_count = 0
        current_date = start_date
        
        while current_date <= end_date:
            # Check if this day of the week is selected (0=Monday, 6=Sunday)
            if current_date.weekday() in selected_days:
                # Calculate trip costs using the service
                total_miles = personal_miles + business_miles
                trip_cost, gallons_used, avg_mpg = VehicleService.calculate_trip_cost(
                    vehicle_id, total_miles, current_date
                )
                
                # Create new trip
                new_trip = Trip(
                    vehicle_id=vehicle_id,
                    date=current_date,
                    journey_description=journey_description,
                    personal_miles=personal_miles,
                    business_miles=business_miles,
                    approx_mpg=avg_mpg,
                    gallons_used=gallons_used,
                    trip_cost=trip_cost
                )
                db.session.add(new_trip)
                created_count += 1
            
            # Move to next day
            current_date += timedelta(days=1)
        
        db.session.commit()
        flash(f'Successfully created {created_count} trip(s)', 'success')
    except ValueError as ve:
        db.session.rollback()
        flash(f'Invalid input: {str(ve)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating trips: {str(e)}', 'danger')
    
    return redirect(url_for('vehicles.trips'))
