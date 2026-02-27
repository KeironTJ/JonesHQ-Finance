"""
Fuel Forecasting Service
========================
Predicts future fuel refill dates from the vehicle's planned trip schedule and
creates/maintains forecasted bank Transactions for those refills.

How predictions work
--------------------
1. Walk all Trip rows for the vehicle in date order, accumulating gallons consumed
   (miles / avg_MPG).
2. When cumulative consumption hits the refill threshold (tank_size × refuel_threshold_pct),
   record a predicted refill date (the previous trip's date) and reset the counter.
3. An actual FuelRecord on a given date resets the counter (tank was filled that day).

Forecasted transactions
-----------------------
``sync_forecasted_transactions()`` deletes all future forecasted fuel transactions for
the vehicle and recreates them from the latest predictions.  When a real FuelRecord is
logged, ``link_fuel_record_to_transaction()`` promotes the nearest forecasted transaction
to is_forecasted=False / is_paid=True (or creates a new actual transaction if none is found).

Primary entry points
--------------------
  predict_refills()                   — list of predicted refill dates + costs
  sync_forecasted_transactions()      — delete stale forecasts and recreate from predictions
  link_fuel_record_to_transaction()   — convert a forecasted transaction to actual on fill
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from extensions import db
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.transactions import Transaction
from models.categories import Category
from services.payday_service import PaydayService
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class FuelForecastingService:
    """
    Predict future fuel refills from trip data and maintain forecasted transactions.

    All price calculations: price_per_litre is stored in pence.  Costs are computed
    as (litres × price_pence) / 100 to convert to £.  UK gallon conversion factor:
    1 gallon = 4.54609 litres.
    """
    
    @staticmethod
    def get_average_fuel_price(vehicle_id, recent_count=5):
        """Get average fuel price per litre from recent fills"""
        recent_fills = family_query(FuelRecord).filter_by(
            vehicle_id=vehicle_id
        ).filter(
            FuelRecord.price_per_litre > 0
        ).order_by(FuelRecord.date.desc()).limit(recent_count).all()
        
        if not recent_fills:
            return Decimal('150.0')  # Default 150p per litre
        
        avg_price = sum(float(f.price_per_litre) for f in recent_fills) / len(recent_fills)
        return Decimal(str(round(avg_price, 2)))
    
    @staticmethod
    def get_average_mpg(vehicle_id, recent_count=10):
        """Get average MPG from recent fills"""
        recent_fills = family_query(FuelRecord).filter_by(
            vehicle_id=vehicle_id
        ).filter(
            FuelRecord.mpg.isnot(None),
            FuelRecord.mpg > 0
        ).order_by(FuelRecord.date.desc()).limit(recent_count).all()
        
        if not recent_fills:
            return None
        
        avg_mpg = sum(float(f.mpg) for f in recent_fills) / len(recent_fills)
        return round(avg_mpg, 1)
    
    @staticmethod
    def calculate_trip_fuel_consumption(vehicle_id):
        """
        Calculate cumulative fuel consumption from trips.
        Returns dict with date -> {gallons_used, cumulative_gallons, estimated_cost}
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return {}
        
        # Get average MPG for this vehicle
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return {}
        
        # Get average fuel price
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)
        
        # Get all trips ordered by date
        trips = family_query(Trip).filter_by(vehicle_id=vehicle_id).order_by(Trip.date.asc()).all()
        
        # Get all actual fuel records
        fuel_records = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.asc()).all()
        fuel_dates = {f.date for f in fuel_records}
        
        consumption_data = {}
        cumulative_gallons = 0.0
        last_reset_date = None
        
        for trip in trips:
            # Reset cumulative if there was a fuel fill on this date
            if trip.date in fuel_dates:
                cumulative_gallons = 0.0
                last_reset_date = trip.date
                continue
            
            # Calculate fuel used for this trip
            if trip.total_miles and trip.total_miles > 0:
                gallons_used = trip.total_miles / avg_mpg
                cumulative_gallons += gallons_used
                
                # Estimate cost (price in pence, convert to pounds)
                litres = gallons_used * 4.54609
                cost = (litres * float(avg_price)) / 100
                
                consumption_data[trip.date] = {
                    'gallons_used': round(gallons_used, 2),
                    'cumulative_gallons': round(cumulative_gallons, 2),
                    'estimated_cost': round(cost, 2),
                    'miles': trip.total_miles,
                    'last_reset_date': last_reset_date
                }
        
        return consumption_data
    
    @staticmethod
    def predict_refills(vehicle_id):
        """
        Predict when refills will be needed based on tank capacity.
        Returns list of predicted refill dates with costs.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return []
        
        tank_capacity = float(vehicle.tank_size)
        refill_threshold = tank_capacity * (float(vehicle.refuel_threshold_pct or 95) / 100)
        
        # Get average MPG and price
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return []
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)
        
        # Get all trips ordered by date
        trips = family_query(Trip).filter_by(vehicle_id=vehicle_id).order_by(Trip.date.asc()).all()
        
        # Get all actual fuel records to know when tank was filled
        fuel_records = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.asc()).all()
        fuel_dates = {f.date for f in fuel_records}
        
        predicted_refills = []
        cumulative_gallons = 0.0
        last_reset_date = None
        previous_trip_date = None
        
        for trip in trips:
            # Reset cumulative if there was an actual fuel fill on this date
            if trip.date in fuel_dates:
                cumulative_gallons = 0.0
                last_reset_date = trip.date
                previous_trip_date = trip.date
                continue
            
            # Calculate fuel needed for this trip
            if trip.total_miles and trip.total_miles > 0:
                gallons_needed = trip.total_miles / avg_mpg
                
                # Check if THIS trip would push us over the threshold
                if cumulative_gallons + gallons_needed >= refill_threshold:
                    # Predict refill BEFORE this trip (use previous trip date or day before)
                    from datetime import timedelta
                    refill_date = previous_trip_date if previous_trip_date else (trip.date - timedelta(days=1))
                    
                    # Refill amount is the cumulative consumed (capped at tank capacity)
                    refill_gallons = min(cumulative_gallons, tank_capacity)
                    litres = refill_gallons * 4.54609
                    cost = (litres * float(avg_price)) / 100
                    
                    predicted_refills.append({
                        'date': refill_date,
                        'gallons': round(refill_gallons, 2),
                        'cost': round(cost, 2),
                        'cumulative_since_last': cumulative_gallons,
                        'last_reset_date': last_reset_date
                    })
                    
                    # Reset cumulative after refill
                    cumulative_gallons = 0.0
                    last_reset_date = refill_date
                
                # Add this trip's consumption
                cumulative_gallons += gallons_needed
                previous_trip_date = trip.date
        
        return predicted_refills
    
    @staticmethod
    def create_forecasted_transaction(vehicle_id, refill_date, cost, description=None):
        """Create a forecasted transaction for a predicted refill"""
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return None
        
        # Get fuel category
        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return None
        
        # Get Fuel Station vendor
        from models.vendors import Vendor
        fuel_vendor = family_query(Vendor).filter_by(name='Fuel Station').first()
        
        # Get default fuel account if vehicle doesn't have one set
        from models.accounts import Account
        account_id = vehicle.fuel_account_id
        if not account_id:
            # Default to Nationwide Current Account
            current_account = family_query(Account).filter_by(name='Nationwide Current Account').first()
            account_id = current_account.id if current_account else None
        
        # Check if forecasted transaction already exists for this date
        existing = family_query(Transaction).filter_by(
            transaction_date=refill_date,
            is_forecasted=True,
            category_id=fuel_category.id
        ).filter(
            Transaction.description.like(f'%{vehicle.registration}%')
        ).first()
        
        if existing:
            # Update existing forecasted transaction
            existing.amount = -Decimal(str(cost))
            existing.vendor_id = fuel_vendor.id if fuel_vendor else existing.vendor_id
            existing.account_id = account_id
            return existing
        
        # Calculate payday period
        _, _, payday_period = PaydayService.get_payday_period(refill_date.year, refill_date.month)
        
        # Create new forecasted transaction
        transaction = Transaction(
            account_id=account_id,
            category_id=fuel_category.id,
            vendor_id=fuel_vendor.id if fuel_vendor else None,
            amount=-Decimal(str(cost)),
            transaction_date=refill_date,
            description=description or f'Forecasted fuel - {vehicle.registration}',
            item=f'{vehicle.name} - Predicted refill',
            is_forecasted=True,
            is_paid=False,
            payday_period=payday_period,
            year_month=refill_date.strftime('%Y-%m'),
            day_name=refill_date.strftime('%a')
        )
        
        db.session.add(transaction)
        return transaction
    
    @staticmethod
    def sync_forecasted_transactions(vehicle_id):
        """
        Rebuild all future forecasted fuel transactions for a vehicle.

        Deletes any existing future forecasted transactions in the 'Transportation - Fuel'
        category matching the vehicle's registration, then calls predict_refills() and
        creates a new forecasted transaction for each predicted date >= today.

        Call this after adding/editing Trip or FuelRecord rows to keep forecasts current.
        Also called internally by link_fuel_record_to_transaction() after a fill is logged.

        Side effects:
            Commits the session.
        """
        # Delete old forecasted transactions for this vehicle
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return
        
        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return
        
        # Delete future forecasted fuel transactions for this vehicle
        today = date.today()
        family_query(Transaction).filter(
            Transaction.transaction_date >= today,
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id,
            Transaction.description.like(f'%{vehicle.registration}%')
        ).delete(synchronize_session=False)
        
        # Get predicted refills
        predicted_refills = FuelForecastingService.predict_refills(vehicle_id)
        
        # Create forecasted transactions
        for refill in predicted_refills:
            if refill['date'] >= today:
                FuelForecastingService.create_forecasted_transaction(
                    vehicle_id=vehicle_id,
                    refill_date=refill['date'],
                    cost=refill['cost']
                )
        
        db.session.commit()
    
    @staticmethod
    def link_fuel_record_to_transaction(fuel_record_id):
        """
        Convert a forecasted fuel transaction to actual when a real fill-up is recorded.

        Looks for a forecasted transaction within ±3 days of the fill date for the same
        vehicle registration.  If found, updates it to is_forecasted=False, is_paid=True
        with the actual amount and date.  If not found, creates a new actual transaction.

        In both cases, links the record via fuel_record.linked_transaction_id and calls
        sync_forecasted_transactions() to regenerate future forecasts.

        Args:
            fuel_record_id: ID of the FuelRecord that was just created.

        Returns:
            Transaction — the created or updated transaction, or None if fuel record not found.

        Side effects:
            Commits the session.
        """
        fuel_record = family_get(FuelRecord, fuel_record_id)
        if not fuel_record:
            return None
        
        vehicle = fuel_record.vehicle
        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        
        if not fuel_category:
            return None
        
        # Get Fuel Station vendor
        from models.vendors import Vendor
        fuel_vendor = family_query(Vendor).filter_by(name='Fuel Station').first()
        
        # Get default fuel account if vehicle doesn't have one set
        from models.accounts import Account
        account_id = vehicle.fuel_account_id
        if not account_id:
            # Default to Nationwide Current Account
            current_account = family_query(Account).filter_by(name='Nationwide Current Account').first()
            account_id = current_account.id if current_account else None
        
        # Look for forecasted transaction on or near this date
        forecasted = family_query(Transaction).filter(
            Transaction.transaction_date >= fuel_record.date - timedelta(days=3),
            Transaction.transaction_date <= fuel_record.date + timedelta(days=3),
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id,
            Transaction.description.like(f'%{vehicle.registration}%')
        ).first()
        
        if forecasted:
            # Replace forecasted with actual
            forecasted.amount = -fuel_record.cost
            forecasted.transaction_date = fuel_record.date
            forecasted.is_forecasted = False
            forecasted.is_paid = True
            forecasted.description = f'Fuel - {vehicle.registration}'
            forecasted.item = f'{vehicle.name} - {fuel_record.gallons} gal @ £{fuel_record.cost}'
            forecasted.account_id = account_id
            forecasted.vendor_id = fuel_vendor.id if fuel_vendor else forecasted.vendor_id
            
            # Update computed fields
            forecasted.year_month = fuel_record.date.strftime('%Y-%m')
            forecasted.day_name = fuel_record.date.strftime('%a')
            forecasted.payday_period = PaydayService.get_period_for_date(fuel_record.date)
            
            fuel_record.linked_transaction_id = forecasted.id
            transaction = forecasted
        else:
            # Create new actual transaction
            payday_period = PaydayService.get_period_for_date(fuel_record.date)
            
            transaction = Transaction(
                account_id=account_id,
                category_id=fuel_category.id,
                vendor_id=fuel_vendor.id if fuel_vendor else None,
                amount=-fuel_record.cost,
                transaction_date=fuel_record.date,
                description=f'Fuel - {vehicle.registration}',
                item=f'{vehicle.name} - {fuel_record.gallons} gal @ £{fuel_record.cost}',
                is_forecasted=False,
                is_paid=True,
                payday_period=payday_period,
                year_month=fuel_record.date.strftime('%Y-%m'),
                day_name=fuel_record.date.strftime('%a')
            )
            
            db.session.add(transaction)
            db.session.flush()
            
            fuel_record.linked_transaction_id = transaction.id
        
        db.session.commit()
        
        # Resync forecasted transactions for this vehicle
        FuelForecastingService.sync_forecasted_transactions(vehicle.id)
        
        return transaction
