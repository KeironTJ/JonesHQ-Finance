"""
Vehicle Service
===============
Fuel metrics, trip cost estimation, and bank-transaction creation for vehicle records.

Fuel metrics
------------
All MPG and per-mile cost calculations are derived by comparing consecutive FuelRecord
rows (current mileage minus previous fill mileage).  The first fill for a vehicle has
no previous record, so actual_miles=0 and MPG=0 for that entry.

Primary entry points
--------------------
  calculate_fuel_metrics()    — derive MPG, per-mile cost from a new fill vs previous
  get_vehicle_stats()         — aggregate totals and averages across all fills
  calculate_trip_cost()       — estimated cost for a trip using recent MPG + price data
  estimate_monthly_fuel_cost()— rolling 3-month average monthly fuel cost
  create_fuel_transaction()   — create a bank Transaction for an actual fuel purchase
"""
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.transactions import Transaction
from models.categories import Category
from models.accounts import Account
from extensions import db
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import func
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class VehicleService:
    """
    Fuel efficiency metrics, trip cost estimation, and bank-transaction creation.

    All cost/price values use Decimal internally.  Prices are stored in pence-per-litre
    for fuel; costs and trip expenses are stored in pounds.
    """

    @staticmethod
    def create_vehicle(data):
        vehicle = Vehicle(
            family_id=get_family_id(),
            name=data.get('name'),
            make=data.get('make'),
            model=data.get('model'),
            registration=data.get('registration', '').upper(),
            tank_size=Decimal(data['tank_size']) if data.get('tank_size') else None,
            fuel_type=data.get('fuel_type'),
            year=int(data['year']) if data.get('year') else None,
            starting_mileage=(
                int(data['starting_mileage'])
                if data.get('starting_mileage') else None
            ),
            fuel_account_id=(
                int(data['fuel_account_id'])
                if data.get('fuel_account_id') else None
            ),
            refuel_threshold_pct=Decimal(
                data.get('refuel_threshold_pct') or '95'
            ),
            is_active=True,
        )
        db.session.add(vehicle)
        db.session.commit()
        return vehicle

    @staticmethod
    def update_vehicle(vehicle_id, data):
        vehicle = family_get_or_404(Vehicle, vehicle_id)
        vehicle.name = data.get('name', vehicle.name)
        vehicle.make = data.get('make', vehicle.make)
        vehicle.model = data.get('model', vehicle.model)
        vehicle.registration = data.get('registration', vehicle.registration).upper()
        vehicle.fuel_type = data.get('fuel_type', vehicle.fuel_type)
        vehicle.is_active = data.get('is_active') == 'on'
        if data.get('tank_size'):
            vehicle.tank_size = Decimal(data['tank_size'])
        if data.get('refuel_threshold_pct'):
            vehicle.refuel_threshold_pct = Decimal(data['refuel_threshold_pct'])
        if data.get('year'):
            vehicle.year = int(data['year'])
        vehicle.fuel_account_id = (
            int(data['fuel_account_id']) if data.get('fuel_account_id') else None
        )
        db.session.commit()
        return vehicle

    @staticmethod
    def delete_vehicle(vehicle_id):
        vehicle = family_get_or_404(Vehicle, vehicle_id)
        name = vehicle.name
        db.session.delete(vehicle)
        db.session.commit()
        return name

    @staticmethod
    def create_fuel_record(data):
        vehicle_id = int(data['vehicle_id'])
        fuel_date = date.fromisoformat(data['date'])
        price_per_litre = Decimal(data['price_per_litre'])
        mileage = int(data['mileage'])
        cost = Decimal(data['cost'])
        gallons = Decimal(data['gallons'])
        metrics = VehicleService.calculate_fuel_metrics(
            vehicle_id, mileage, gallons, cost, fuel_date
        )
        fuel_record = FuelRecord(
            family_id=get_family_id(),
            vehicle_id=vehicle_id,
            date=fuel_date,
            price_per_litre=price_per_litre,
            mileage=mileage,
            cost=cost,
            gallons=gallons,
            actual_miles=metrics[0],
            mpg=metrics[1],
            price_per_mile=metrics[2],
            last_fill_date=metrics[3],
            actual_cumulative_miles=metrics[4],
            is_partial_fill=data.get('is_partial_fill') == '1',
        )
        db.session.add(fuel_record)
        db.session.commit()
        return fuel_record

    @staticmethod
    def update_fuel_record(fuel_id, data):
        fuel_record = family_get_or_404(FuelRecord, fuel_id)
        fuel_record.date = date.fromisoformat(data['date'])
        fuel_record.price_per_litre = Decimal(data['price_per_litre'])
        fuel_record.mileage = int(data['mileage'])
        fuel_record.cost = Decimal(data['cost'])
        fuel_record.gallons = Decimal(data['gallons'])
        fuel_record.is_partial_fill = data.get('is_partial_fill') == '1'
        metrics = VehicleService.calculate_fuel_metrics(
            fuel_record.vehicle_id,
            fuel_record.mileage,
            fuel_record.gallons,
            fuel_record.cost,
            fuel_record.date,
        )
        fuel_record.actual_miles = metrics[0]
        fuel_record.mpg = metrics[1]
        fuel_record.price_per_mile = metrics[2]
        fuel_record.last_fill_date = metrics[3]
        fuel_record.actual_cumulative_miles = metrics[4]
        db.session.commit()
        return fuel_record

    @staticmethod
    def delete_fuel_record(fuel_id):
        fuel_record = family_get_or_404(FuelRecord, fuel_id)
        vehicle_id = fuel_record.vehicle_id
        db.session.delete(fuel_record)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def create_trip(data):
        vehicle_id = int(data['vehicle_id'])
        trip_date = date.fromisoformat(data['date'])
        trip_type = data.get('trip_type', 'personal')
        miles = int(data.get('miles') or 0)
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
            vehicle_id, miles, trip_date
        )
        latest_fuel = VehicleService.get_latest_fuel_record(vehicle_id)
        previous_trip = family_query(Trip).filter(
            Trip.vehicle_id == vehicle_id, Trip.date < trip_date
        ).order_by(Trip.date.desc()).first()
        cumulative_miles = (
            (previous_trip.cumulative_total_miles or 0) + miles
            if previous_trip else miles
        )
        cumulative_gallons = (
            (previous_trip.cumulative_gallons or Decimal('0')) + gallons_used
            if previous_trip else gallons_used
        )
        trip = Trip(
            family_id=get_family_id(),
            vehicle_id=vehicle_id,
            date=trip_date,
            month=trip_date.strftime('%Y-%m'),
            week=f'{trip_date.isocalendar()[1]:02d}-{trip_date.year}',
            day_name=trip_date.strftime('%A'),
            personal_miles=miles if trip_type == 'personal' else 0,
            business_miles=miles if trip_type == 'business' else 0,
            total_miles=miles,
            cumulative_total_miles=cumulative_miles,
            journey_description=data.get('journey_description', ''),
            school_holidays=data.get('school_holidays', ''),
            approx_mpg=approx_mpg,
            gallons_used=gallons_used,
            cumulative_gallons=cumulative_gallons,
            trip_cost=trip_cost,
            fuel_cost=Decimal('0'),
            vehicle_last_fill=latest_fuel.date if latest_fuel else None,
        )
        db.session.add(trip)
        db.session.commit()
        return trip

    @staticmethod
    def update_trip(trip_id, data):
        trip = family_get_or_404(Trip, trip_id)
        trip.date = date.fromisoformat(data['date'])
        trip_type = data.get('trip_type', 'personal')
        miles = int(data.get('miles') or 0)
        trip.personal_miles = miles if trip_type == 'personal' else 0
        trip.business_miles = miles if trip_type == 'business' else 0
        trip.total_miles = miles
        trip.journey_description = data.get('journey_description', '')
        trip.school_holidays = data.get('school_holidays', '')
        trip.trip_cost, trip.gallons_used, trip.approx_mpg = VehicleService.calculate_trip_cost(
            trip.vehicle_id, miles, trip.date
        )
        db.session.commit()
        return trip

    @staticmethod
    def delete_trip(trip_id):
        trip = family_get_or_404(Trip, trip_id)
        vehicle_id = trip.vehicle_id
        db.session.delete(trip)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def bulk_create_trips(data):
        vehicle_id = int(data['vehicle_id'])
        start_date = date.fromisoformat(data['start_date'])
        end_date = date.fromisoformat(data['end_date'])
        if start_date > end_date:
            raise ValueError('Start date must be before or equal to end date')
        selected_days = {int(day) for day in data.getlist('days')}
        if not selected_days:
            raise ValueError('At least one day must be selected')

        miles = Decimal(data.get('miles') or 0)
        miles_int = int(miles)
        trip_type = data.get('trip_type', 'personal')
        created = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() in selected_days:
                trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
                    vehicle_id, miles, current_date
                )
                trip = Trip(
                    family_id=get_family_id(),
                    vehicle_id=vehicle_id,
                    date=current_date,
                    month=current_date.strftime('%Y-%m'),
                    week=f'{current_date.isocalendar()[1]:02d}-{current_date.year}',
                    day_name=current_date.strftime('%A'),
                    personal_miles=miles_int if trip_type == 'personal' else 0,
                    business_miles=miles_int if trip_type == 'business' else 0,
                    total_miles=miles_int,
                    journey_description=data.get('journey_description', ''),
                    approx_mpg=approx_mpg,
                    gallons_used=gallons_used,
                    trip_cost=trip_cost,
                    fuel_cost=Decimal('0'),
                )
                db.session.add(trip)
                created.append(trip)
            current_date += timedelta(days=1)
        db.session.commit()
        return created

    @staticmethod
    def calculate_fuel_metrics(vehicle_id, current_mileage, gallons, cost, fuel_date):
        """
        Derive fuel metrics for a new fill-up by comparing to the previous record.

        Args:
            vehicle_id:       ID of the Vehicle.
            current_mileage:  Odometer reading at this fill-up.
            gallons:          Gallons added.
            cost:             Total cost in £ (Decimal).
            fuel_date:        Date of this fill-up (used to find the previous fill).

        Returns:
            (actual_miles, mpg, price_per_mile, last_fill_date, cumulative_miles)
            All zero/None for the first fill (no prior record to compare against).
        """
        # Get the most recent fuel record before this one
        previous_fill = family_query(FuelRecord).filter(
            FuelRecord.vehicle_id == vehicle_id,
            FuelRecord.date < fuel_date
        ).order_by(FuelRecord.date.desc()).first()
        
        if previous_fill:
            actual_miles = current_mileage - previous_fill.mileage
            mpg = Decimal(actual_miles) / gallons if gallons > 0 else Decimal('0')
            price_per_mile = cost / Decimal(actual_miles) if actual_miles > 0 else Decimal('0')
            last_fill_date = previous_fill.date
            cumulative_miles = (previous_fill.actual_cumulative_miles or 0) + actual_miles
        else:
            # First fill for this vehicle
            actual_miles = 0
            mpg = Decimal('0')
            price_per_mile = Decimal('0')
            last_fill_date = None
            cumulative_miles = 0
        
        return actual_miles, mpg, price_per_mile, last_fill_date, cumulative_miles
    
    @staticmethod
    def get_latest_fuel_record(vehicle_id):
        """Get the most recent fuel record for a vehicle"""
        return family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.desc()).first()
    
    @staticmethod
    def calculate_fuel_efficiency(vehicle_id, num_records=10):
        """Calculate average fuel efficiency for a vehicle"""
        records = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(
            FuelRecord.date.desc()
        ).limit(num_records).all()
        
        if not records:
            return Decimal('0')
        
        avg_mpg = sum([r.mpg or Decimal('0') for r in records]) / len(records)
        return avg_mpg
    
    @staticmethod
    def get_total_fuel_cost(vehicle_id, start_date=None, end_date=None):
        """Calculate total fuel costs for a vehicle"""
        query = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id)
        
        if start_date:
            query = query.filter(FuelRecord.date >= start_date)
        if end_date:
            query = query.filter(FuelRecord.date <= end_date)
        
        total = family_query(FuelRecord).with_entities(func.sum(FuelRecord.cost)).filter(
            FuelRecord.vehicle_id == vehicle_id
        )
        if start_date:
            total = total.filter(FuelRecord.date >= start_date)
        if end_date:
            total = total.filter(FuelRecord.date <= end_date)
        
        result = total.scalar()
        return result or Decimal('0')
    
    @staticmethod
    def estimate_monthly_fuel_cost(vehicle_id):
        """Estimate monthly fuel costs based on historical data"""
        # Get last 3 months of data
        three_months_ago = date.today() - timedelta(days=90)
        total_cost = VehicleService.get_total_fuel_cost(vehicle_id, three_months_ago)
        
        # Average per month
        monthly_avg = total_cost / Decimal('3')
        return monthly_avg
    
    @staticmethod
    def get_vehicle_stats(vehicle_id):
        """Get comprehensive stats for a vehicle"""
        fuel_records = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).all()
        
        if not fuel_records:
            return {
                'avg_mpg': Decimal('0'),
                'total_cost': Decimal('0'),
                'total_miles': 0,
                'total_gallons': Decimal('0'),
                'avg_price_per_gallon': Decimal('0')
            }
        
        total_cost = sum([f.cost for f in fuel_records])
        total_gallons = sum([f.gallons for f in fuel_records])
        total_miles = max([f.actual_cumulative_miles or 0 for f in fuel_records])
        
        # Calculate average MPG from records that have MPG
        mpg_records = [f.mpg for f in fuel_records if f.mpg and f.mpg > 0]
        avg_mpg = sum(mpg_records) / len(mpg_records) if mpg_records else Decimal('0')
        
        avg_price_per_gallon = total_cost / total_gallons if total_gallons > 0 else Decimal('0')
        
        return {
            'avg_mpg': avg_mpg,
            'total_cost': total_cost,
            'total_miles': total_miles,
            'total_gallons': total_gallons,
            'avg_price_per_gallon': avg_price_per_gallon
        }
    
    @staticmethod
    def calculate_trip_cost(vehicle_id, miles, trip_date):
        """Calculate estimated cost for a trip based on recent MPG and fuel prices"""
        # Get average MPG from last 10 fuel records before the trip date
        recent_fuels = family_query(FuelRecord).filter(
            FuelRecord.vehicle_id == vehicle_id,
            FuelRecord.date <= trip_date,
            FuelRecord.mpg.isnot(None),
            FuelRecord.mpg > 0
        ).order_by(FuelRecord.date.desc()).limit(10).all()
        
        if not recent_fuels:
            # Try to get any fuel record for this vehicle
            latest_fuel = VehicleService.get_latest_fuel_record(vehicle_id)
            if not latest_fuel or not latest_fuel.mpg or latest_fuel.mpg == 0:
                return Decimal('0'), Decimal('0'), Decimal('0')
            avg_mpg = latest_fuel.mpg
            price_per_gallon = latest_fuel.cost / latest_fuel.gallons if latest_fuel.gallons > 0 else Decimal('0')
        else:
            # Calculate average MPG from recent fills
            avg_mpg = sum([f.mpg for f in recent_fuels]) / Decimal(len(recent_fuels))
            
            # Get average price per gallon from recent fills (last 3)
            recent_price_records = recent_fuels[:3]
            avg_price_per_gallon = sum([
                f.cost / f.gallons if f.gallons > 0 else Decimal('0') 
                for f in recent_price_records
            ]) / Decimal(len(recent_price_records))
            price_per_gallon = avg_price_per_gallon
        
        gallons_used = Decimal(miles) / avg_mpg if avg_mpg > 0 else Decimal('0')
        trip_cost = gallons_used * price_per_gallon
        
        return trip_cost, gallons_used, avg_mpg
    
    @staticmethod
    def create_fuel_transaction(fuel_record, account_id):
        """Create a transaction for a fuel purchase"""
        from services.payday_service import PaydayService
        
        # Get or create Fuel category
        category = family_query(Category).filter(
            db.func.lower(Category.name) == 'fuel'
        ).first()
        
        if not category:
            category = Category(
                name='Fuel',
                category_type='Expense',
                head_budget='General',
                sub_budget='Fuel'
            )
            db.session.add(category)
            db.session.commit()
        
        vehicle = family_get(Vehicle, fuel_record.vehicle_id)
        
        # Calculate year_month and payday_period
        trans_date = fuel_record.date
        year_month = f"{trans_date.year:04d}-{trans_date.month:02d}"
        
        # Determine payday period
        payday_period = None
        start_date, end_date, period_label = PaydayService.get_payday_period(trans_date.year, trans_date.month)
        if start_date <= trans_date <= end_date:
            payday_period = period_label
        else:
            prev_month = trans_date.month - 1
            prev_year = trans_date.year
            if prev_month < 1:
                prev_month = 12
                prev_year -= 1
            start_date, end_date, period_label = PaydayService.get_payday_period(prev_year, prev_month)
            if start_date <= trans_date <= end_date:
                payday_period = period_label
        
        # Create transaction
        transaction = Transaction(
            transaction_date=fuel_record.date,
            account_id=account_id,
            category_id=category.id,
            amount=-fuel_record.cost,  # Negative for expense
            description=f"Fuel - {vehicle.registration}",
            item=f"{vehicle.name} - {fuel_record.gallons:.2f} gal @ {fuel_record.price_per_litre:.1f}p/L",
            is_paid=True,
            payment_type='Card Payment',
            year_month=year_month,
            payday_period=payday_period
        )
        db.session.add(transaction)
        db.session.commit()
        
        return transaction
