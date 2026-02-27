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
