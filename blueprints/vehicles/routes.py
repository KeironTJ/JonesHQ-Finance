from flask import render_template, request, redirect, url_for, flash, jsonify
from . import vehicles_bp
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.accounts import Account
from services.vehicle_service import VehicleService
from services.fuel_forecasting_service import FuelForecastingService
from extensions import db
from datetime import datetime, date
from decimal import Decimal


@vehicles_bp.route('/vehicles')
def index():
    """Vehicle tracking dashboard"""
    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.name).all()
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    
    # Get stats for each vehicle
    vehicle_stats = {}
    for vehicle in vehicles:
        vehicle_stats[vehicle.id] = VehicleService.get_vehicle_stats(vehicle.id)
    
    # Get all fuel records
    fuel_records = FuelRecord.query.order_by(FuelRecord.date.desc()).all()
    
    # Get all trips
    trips = Trip.query.order_by(Trip.date.desc()).all()
    
    return render_template(
        'vehicles/index.html',
        vehicles=vehicles,
        accounts=accounts,
        vehicle_stats=vehicle_stats,
        fuel_records=fuel_records,
        trips=trips
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
        db.session.delete(fuel_record)
        db.session.commit()
        
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
