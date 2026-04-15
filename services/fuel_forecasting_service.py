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
        fuel_date_map = {f.date: f for f in fuel_records}
        
        consumption_data = {}
        cumulative_gallons = 0.0
        last_reset_date = None
        
        for trip in trips:
            # Adjust cumulative if there was a fuel fill on this date.
            # Subtract gallons added so partial fills are handled correctly.
            if trip.date in fuel_date_map:
                fill = fuel_date_map[trip.date]
                gallons_added = float(fill.gallons) if fill.gallons else 0.0
                cumulative_gallons = max(0.0, cumulative_gallons - gallons_added)
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

        Uses a merged timeline of trips and fuel fill events sorted by date.
        Fill events are processed before trip events on the same date (fill up,
        then drive).  This means a fill on any date — even one with no trip entry
        — correctly resets the consumption counter, unlike the old date-keyed
        approach that required a trip to exist on the same day as the fill.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return []

        tank_capacity = float(vehicle.tank_size)
        refill_threshold = tank_capacity * (float(vehicle.refuel_threshold_pct or 95) / 100)

        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return []
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)

        trips = family_query(Trip).filter_by(vehicle_id=vehicle_id).order_by(Trip.date.asc()).all()
        fuel_records = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.asc()).all()

        # Build a merged timeline: (date, sort_priority, type, obj)
        # Priority 0 = fill, 1 = trip → fills processed before trips on the same day.
        events = []
        for trip in trips:
            if trip.total_miles and trip.total_miles > 0:
                events.append((trip.date, 1, 'trip', trip))
        for fill in fuel_records:
            events.append((fill.date, 0, 'fill', fill))
        events.sort(key=lambda x: (x[0], x[1]))

        # Seed the cumulative from the last actual fill.
        # deficit_after_fill = gallons consumed before fill − gallons added.
        # A full fill → deficit ≈ 0.  Clamped to 0 if more filled than consumed.
        last_fill = fuel_records[-1] if fuel_records else None
        if last_fill and last_fill.gallons:
            if last_fill.actual_miles:
                gallons_consumed_before_fill = last_fill.actual_miles / avg_mpg
                initial_deficit = max(0.0, gallons_consumed_before_fill - float(last_fill.gallons))
            else:
                initial_deficit = 0.0
        else:
            initial_deficit = 0.0

        predicted_refills = []
        cumulative_gallons = initial_deficit
        last_reset_date = last_fill.date if last_fill else None
        prev_event_date = last_fill.date if last_fill else None

        for (event_date, _priority, event_type, event_obj) in events:
            # Skip events on or before the last actual fill — already seeded above.
            if last_fill and event_date <= last_fill.date:
                if event_type == 'fill':
                    prev_event_date = event_date
                continue

            if event_type == 'fill':
                # Actual fill on a future date (decrement cumulative, don't reset to 0
                # so partial fills are handled correctly).
                gallons_added = float(event_obj.gallons) if event_obj.gallons else 0.0
                cumulative_gallons = max(0.0, cumulative_gallons - gallons_added)
                last_reset_date = event_date
                prev_event_date = event_date

            elif event_type == 'trip':
                gallons_needed = event_obj.total_miles / avg_mpg

                if cumulative_gallons + gallons_needed >= refill_threshold:
                    # This trip would cross the threshold — predict a fill before it.
                    refill_date = prev_event_date if prev_event_date else (event_date - timedelta(days=1))

                    refill_gallons = min(cumulative_gallons, tank_capacity)
                    litres = refill_gallons * 4.54609
                    cost = (litres * float(avg_price)) / 100

                    predicted_refills.append({
                        'date': refill_date,
                        'gallons': round(refill_gallons, 2),
                        'cost': round(cost, 2),
                        'cumulative_since_last': round(cumulative_gallons, 2),
                        'trigger_trip_date': event_date,
                        'last_reset_date': last_reset_date,
                    })

                    cumulative_gallons = 0.0
                    last_reset_date = refill_date

                cumulative_gallons += gallons_needed
                prev_event_date = event_date

        return predicted_refills
    
    @staticmethod
    def get_tank_status(vehicle_id):
        """
        Return the current estimated tank state for a vehicle.

        Walks the merged trip + fill timeline from the last actual fill forward,
        subtracting gallons consumed by each trip.  Returns a dict:

            last_fill_date          date | None
            last_fill_gallons       float | None   — gallons added at last fill
            miles_since_fill        int            — miles driven since last fill
            gallons_consumed        float          — estimated gallons used since last fill
            gallons_remaining       float          — estimated gallons left in tank
            tank_pct                float 0–100    — % of tank capacity remaining
            estimated_range_miles   int            — approx miles left before empty
            estimated_fill_date     date | None    — projected date threshold is hit
            days_until_refill       int | None     — days from today until threshold
            estimated_fill_cost     float          — estimated cost of next fill-up (£)
            tank_capacity           float
            avg_mpg                 float | None

        Returns None if there is insufficient data to compute a level.
        """
        from datetime import date as date_type
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return None

        tank_capacity = float(vehicle.tank_size)
        refill_threshold = tank_capacity * (float(vehicle.refuel_threshold_pct or 95) / 100)
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)

        if not avg_mpg:
            return None

        all_fills = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.asc()).all()
        all_trips = family_query(Trip).filter_by(
            vehicle_id=vehicle_id
        ).filter(Trip.total_miles > 0).order_by(Trip.date.asc()).all()

        last_fill = all_fills[-1] if all_fills else None
        today = date_type.today()

        # Walk the full merged timeline to compute current tank level and
        # miles since last fill.  Fills add gallons (capped at tank_capacity),
        # trips subtract.  First fill seeds the tank at gallons_added.
        # We track miles_since_fill inside the walk so it resets on any fill,
        # matching the same ordering logic as the tank level calculation.
        events = []
        for trip in all_trips:
            events.append((trip.date, 1, 'trip', trip))
        for fill in all_fills:
            events.append((fill.date, 0, 'fill', fill))
        events.sort(key=lambda x: (x[0], x[1]))

        has_fill = False
        tank_level = 0.0
        miles_since_fill = 0

        for (_event_date, _priority, event_type, event_obj) in events:
            # Only walk up to today — future pre-logged trips must not drain
            # the current estimated tank level.
            if _event_date > today:
                break
            if event_type == 'fill':
                gallons_added = float(event_obj.gallons) if event_obj.gallons else 0.0
                if not has_fill:
                    tank_level = gallons_added  # first fill: assume was empty
                    has_fill = True
                else:
                    tank_level = min(tank_capacity, tank_level + gallons_added)
                miles_since_fill = 0  # reset on every fill
            elif event_type == 'trip' and has_fill:
                gallons_used = event_obj.total_miles / avg_mpg
                tank_level = max(0.0, tank_level - gallons_used)
                miles_since_fill += event_obj.total_miles

        if not has_fill:
            return None

        gallons_remaining = tank_level
        gallons_consumed = miles_since_fill / avg_mpg  # used for display only

        tank_pct = min(100.0, (gallons_remaining / tank_capacity) * 100)
        # Miles to empty (classic "est. range")
        estimated_range = int(gallons_remaining * avg_mpg)

        # Days until refill threshold is reached
        # gallons_until_threshold = usable gallons before the predicted-fill alert fires
        gallons_until_threshold = max(0.0, gallons_remaining - (tank_capacity - refill_threshold))
        miles_to_refill = int(gallons_until_threshold * avg_mpg)

        # avg_daily_miles: only count actual past trips (not future bulk-added ones)
        thirty_days_ago = today - timedelta(days=30)
        recent_miles = sum(
            t.total_miles for t in all_trips
            if thirty_days_ago <= t.date <= today and t.total_miles
        )
        avg_daily_miles = recent_miles / 30.0

        if avg_daily_miles > 0 and miles_to_refill > 0:
            days_until_refill = int(miles_to_refill / avg_daily_miles)
            estimated_fill_date = today + timedelta(days=days_until_refill)
        elif miles_to_refill <= 0:
            days_until_refill = 0
            estimated_fill_date = today
        else:
            days_until_refill = None
            estimated_fill_date = None

        fill_gallons = tank_capacity - gallons_remaining
        fill_litres = fill_gallons * 4.54609
        estimated_fill_cost = round((fill_litres * float(avg_price)) / 100, 2)

        return {
            'last_fill_date': last_fill.date if last_fill else None,
            'last_fill_gallons': float(last_fill.gallons) if last_fill and last_fill.gallons else None,
            'miles_since_fill': miles_since_fill,
            'gallons_consumed': round(gallons_consumed, 2),
            'gallons_remaining': round(gallons_remaining, 2),
            'tank_pct': round(tank_pct, 1),
            'estimated_range_miles': estimated_range,   # miles to empty
            'miles_to_refill': miles_to_refill,          # miles until fill-up threshold
            'estimated_fill_date': estimated_fill_date,
            'days_until_refill': days_until_refill,
            'estimated_fill_cost': estimated_fill_cost,
            'tank_capacity': tank_capacity,
            'avg_mpg': avg_mpg,
        }

    @staticmethod
    def get_trip_tank_levels(vehicle_id):
        """
        Compute the estimated tank level (%) at the END of each trip.

        Walks the merged trip + fill timeline, tracking gallons in the tank.
        Tracking begins from the first actual fill.  Trips with no prior fill
        are omitted from the result (unknown starting level).

        Returns dict {trip_id: tank_pct}.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return {}

        tank_capacity = float(vehicle.tank_size)
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return {}

        all_fills = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.asc()).all()
        all_trips = family_query(Trip).filter_by(
            vehicle_id=vehicle_id
        ).filter(Trip.total_miles > 0).order_by(Trip.date.asc()).all()

        # Merged timeline; fills before trips on same day.
        # Also inject predicted future refill events so the tank column
        # doesn't drain to zero past each predicted fill date.
        predicted = FuelForecastingService.predict_refills(vehicle_id)

        events = []
        for trip in all_trips:
            events.append((trip.date, 1, 'trip', trip))
        for fill in all_fills:
            events.append((fill.date, 0, 'fill', fill))
        for p in predicted:
            # predicted_fill priority 0 — processed before trips on the same day
            events.append((p['date'], 0, 'predicted_fill', p))
        events.sort(key=lambda x: (x[0], x[1]))

        has_fill = False
        tank_level = 0.0
        trip_tank_levels = {}

        for (event_date, _priority, event_type, event_obj) in events:
            if event_type == 'fill':
                gallons_added = float(event_obj.gallons) if event_obj.gallons else 0.0
                if not has_fill:
                    tank_level = gallons_added
                    has_fill = True
                else:
                    tank_level = min(tank_capacity, tank_level + gallons_added)
            elif event_type == 'predicted_fill' and has_fill:
                # Predicted refill — treat as filling back to full
                tank_level = tank_capacity
            elif event_type == 'trip' and has_fill:
                gallons_used = event_obj.total_miles / avg_mpg
                tank_level = max(0.0, tank_level - gallons_used)
                trip_tank_levels[event_obj.id] = round((tank_level / tank_capacity) * 100, 1)

        return trip_tank_levels

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
        payday_period = PaydayService.get_period_for_date(refill_date)
        
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
        Rebuild all forecasted fuel transactions for a vehicle (past and future).

        Deletes all existing forecasted transactions in the 'Transportation - Fuel'
        category matching the vehicle's registration, then calls predict_refills() and
        creates a forecasted transaction for every predicted date.  Past predictions
        represent missed refills when trips weren't kept up to date.

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
        
        # Delete ALL forecasted fuel transactions for this vehicle (past and future)
        # so stale predictions don't accumulate when trips/fills are edited.
        family_query(Transaction).filter(
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id,
            Transaction.description.like(f'%{vehicle.registration}%')
        ).delete(synchronize_session=False)
        
        # Get predicted refills
        predicted_refills = FuelForecastingService.predict_refills(vehicle_id)
        
        # Create forecasted transactions for all predicted refills (past and future).
        # Past ones represent missed fills when trips weren't kept up to date.
        for refill in predicted_refills:
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
