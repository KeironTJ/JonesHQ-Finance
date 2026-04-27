"""
Fuel Forecasting Service
========================
Predicts future fuel refill dates from the vehicle's planned trip schedule and
creates/maintains forecasted bank Transactions for those refills.

How predictions work
--------------------
1. Walk all Trip + FuelRecord rows in date order (fills before trips on the same day).
2. Maintain a ``gallons_remaining`` counter (the estimated tank level).
3. On a **full fill** (is_partial_fill=False): tank resets to tank_capacity.
   On a **partial fill** (is_partial_fill=True): gallons added on top of current level,
   capped at tank_capacity.
4. On a trip: subtract gallons consumed (miles / avg_MPG).  If this would drain the tank
   below the refuel threshold, record a predicted refill BEFORE the trip and reset the
   tank to full.

The threshold is expressed as a percentage of the tank already consumed:
  refuel_threshold_pct = 95  â†’ predict a fill when only 5 % of the tank remains.
  low_threshold_gallons = tank_capacity Ã— (1 âˆ’ refuel_threshold_pct / 100)

Forecasted transactions
-----------------------
``sync_forecasted_transactions()`` deletes all future forecasted fuel transactions for
the vehicle and recreates them from the latest predictions.  When a real FuelRecord is
logged, ``link_fuel_record_to_transaction()`` promotes the nearest forecasted transaction
to is_forecasted=False / is_paid=True (or creates a new actual transaction if none found).

Primary entry points
--------------------
  predict_refills()                   â€” list of predicted refill dates + costs
  sync_forecasted_transactions()      â€” delete stale forecasts and recreate from predictions
  link_fuel_record_to_transaction()   â€” convert a forecasted transaction to actual on fill
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

    Price calculations: price_per_litre is stored in pence.  Costs are computed as
    (litres Ã— price_pence) / 100 to convert to £.  UK gallon: 1 gallon = 4.54609 litres.

    Full-fill vs partial-fill semantics
    ------------------------------------
    is_partial_fill = False (default)
        The tank was topped up fully.  After the fill: gallons_remaining = tank_capacity.
    is_partial_fill = True
        Only some fuel was added.  After the fill:
        gallons_remaining = min(tank_capacity, gallons_remaining + gallons_added).
    """

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def get_average_fuel_price(vehicle_id, recent_count=5):
        """Return average price_per_litre (pence) from the most recent fills."""
        recent_fills = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .filter(FuelRecord.price_per_litre > 0)
            .order_by(FuelRecord.date.desc())
            .limit(recent_count)
            .all()
        )
        if not recent_fills:
            return Decimal('150.0')  # fallback: 150p/litre
        avg = sum(float(f.price_per_litre) for f in recent_fills) / len(recent_fills)
        return Decimal(str(round(avg, 2)))

    @staticmethod
    def get_average_mpg(vehicle_id, recent_count=10):
        """Return average MPG from the most recent fills that have mpg recorded."""
        recent_fills = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .filter(FuelRecord.mpg.isnot(None), FuelRecord.mpg > 0)
            .order_by(FuelRecord.date.desc())
            .limit(recent_count)
            .all()
        )
        if not recent_fills:
            return None
        return round(sum(float(f.mpg) for f in recent_fills) / len(recent_fills), 1)

    # ------------------------------------------------------------------ core logic

    @staticmethod
    def _build_merged_timeline(trips, fuel_records):
        """
        Return a sorted list of (date, priority, event_type, obj) tuples.

        Priority 0 = fill / partial-fill (processed before trips on the same day).
        Priority 1 = trip.
        Trips with zero miles are excluded.

        When multiple events share the same (date, priority) — e.g. several trips
        on the same day — they are ordered by the model's primary key (id) so the
        sequence is deterministic and reflects the order they were recorded.
        """
        events = []
        for trip in trips:
            if trip.total_miles and trip.total_miles > 0:
                events.append((trip.date, 1, 'trip', trip))
        for fill in fuel_records:
            events.append((fill.date, 0, 'fill', fill))
        events.sort(key=lambda x: (x[0], x[1], x[3].id))
        return events

    @staticmethod
    def _apply_fill(tank_level, tank_capacity, fill_obj, has_fill):
        """
        Apply a fill event and return (new_tank_level, new_has_fill).

        First-ever fill seeds the tank (full â†’ tank_capacity; partial â†’ gallons_added).
        Subsequent fills: full â†’ tank_capacity; partial â†’ clamp to tank_capacity.
        """
        gallons_added = float(fill_obj.gallons) if fill_obj.gallons else 0.0
        is_partial = bool(fill_obj.is_partial_fill)

        if not has_fill:
            # Anchor: first recorded fill
            new_level = gallons_added if is_partial else tank_capacity
            return new_level, True

        if is_partial:
            new_level = min(tank_capacity, tank_level + gallons_added)
        else:
            new_level = tank_capacity  # full fill always tops up to max
        return new_level, True

    # ------------------------------------------------------------------ public API

    @staticmethod
    def predict_refills(vehicle_id):
        """
        Predict when refills will be needed based on tank capacity and planned trips.

        Walks the merged trip + fill timeline from the very first fill.  Full fills
        reset the tank to capacity; partial fills add gallons on top of the current
        level.  A predicted refill is inserted before any trip that would drain the
        tank below the low-fuel threshold.

        Returns a list of dicts:
            date                â€” predicted refill date (date of the preceding event)
            gallons             â€” gallons needed to top up at that point
            cost                â€” estimated cost in £
            tank_level_before   â€” estimated gallons in tank just before the fill
            trigger_trip_date   â€” date of the trip that would exhaust the tank
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return []

        tank_capacity = float(vehicle.tank_size)
        # Threshold: predict a fill when tank_level would drop at or below this value
        low_threshold = tank_capacity * (1.0 - float(vehicle.refuel_threshold_pct or 95) / 100)

        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return []
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)

        # Anchor on the last FULL fill-up — it resets the tank to tank_capacity,
        # so everything before it is irrelevant.  Partial-fills since that date
        # are included because they adjust the level before the anchor date's trips.
        today = date.today()

        last_full_fill = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id, is_partial_fill=False)
            .order_by(FuelRecord.date.desc())
            .first()
        )

        anchor_date = last_full_fill.date if last_full_fill else None

        trips = (
            family_query(Trip)
            .filter_by(vehicle_id=vehicle_id)
            .filter(Trip.date >= anchor_date) if anchor_date else
            family_query(Trip).filter_by(vehicle_id=vehicle_id)
        ).order_by(Trip.date.asc()).all()

        fuel_records = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .filter(FuelRecord.date >= anchor_date) if anchor_date else
            family_query(FuelRecord).filter_by(vehicle_id=vehicle_id)
        ).order_by(FuelRecord.date.asc()).all()

        events = FuelForecastingService._build_merged_timeline(trips, fuel_records)

        # Start the tank at full (the anchor is always a full fill)
        predicted_refills = []
        tank_level = tank_capacity if last_full_fill else 0.0
        has_fill = bool(last_full_fill)
        prev_event_date = anchor_date

        for (event_date, _priority, event_type, event_obj) in events:
            if event_type == 'fill':
                tank_level, has_fill = FuelForecastingService._apply_fill(
                    tank_level, tank_capacity, event_obj, has_fill
                )
                prev_event_date = event_date

            elif event_type == 'trip' and has_fill:
                gallons_needed = event_obj.total_miles / avg_mpg

                if tank_level - gallons_needed <= low_threshold:
                    # This trip would cross the threshold â€” predict a fill before it.
                    refill_date = prev_event_date if prev_event_date else (event_date - timedelta(days=1))
                    fill_gallons = tank_capacity - tank_level
                    fill_litres = fill_gallons * 4.54609
                    cost = (fill_litres * float(avg_price)) / 100

                    # Only emit predictions for present/future trips.
                    if event_date >= today:
                        predicted_refills.append({
                            'date': refill_date,
                            'gallons': round(fill_gallons, 2),
                            'cost': round(cost, 2),
                            'tank_level_before': round(tank_level, 2),
                            'trigger_trip_date': event_date,
                            'trigger_trip_id': event_obj.id,
                        })

                    tank_level = tank_capacity  # filled to full (keeps chain intact)

                tank_level = max(0.0, tank_level - gallons_needed)
                prev_event_date = event_date

        return predicted_refills

    @staticmethod
    def get_tank_status(vehicle_id):
        """
        Return the current estimated tank state for a vehicle.

        Walks the merged trip + fill timeline up to today.  Full fills reset the
        tank to capacity; partial fills add gallons on top.  Returns a dict:

            last_fill_date          date | None
            last_fill_gallons       float | None   â€” gallons added at last fill
            last_fill_is_partial    bool
            miles_since_fill        int            â€” miles driven since last fill
            gallons_consumed        float          â€” gallons used since last fill
            gallons_remaining       float          â€” estimated gallons left in tank
            tank_pct                float 0â€“100    â€” % of tank capacity remaining
            estimated_range_miles   int            â€” approx miles left before empty
            miles_to_refill         int            â€” miles until refuel threshold
            estimated_fill_date     date | None    â€” projected date threshold is hit
            days_until_refill       int | None     â€” days from today until threshold
            estimated_fill_cost     float          â€” estimated cost of next fill-up (£)
            tank_capacity           float
            avg_mpg                 float | None

        Returns None if there is insufficient data to compute a level.
        """
        from datetime import date as date_type
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return None

        tank_capacity = float(vehicle.tank_size)
        low_threshold = tank_capacity * (1.0 - float(vehicle.refuel_threshold_pct or 95) / 100)
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)

        if not avg_mpg:
            return None

        all_fills = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .order_by(FuelRecord.date.asc())
            .all()
        )
        all_trips = (
            family_query(Trip)
            .filter_by(vehicle_id=vehicle_id)
            .filter(Trip.total_miles > 0)
            .order_by(Trip.date.asc())
            .all()
        )

        last_fill = all_fills[-1] if all_fills else None
        today = date_type.today()

        events = FuelForecastingService._build_merged_timeline(all_trips, all_fills)

        has_fill = False
        tank_level = 0.0
        miles_since_fill = 0

        for (_event_date, _priority, event_type, event_obj) in events:
            # Only walk up to today â€” future pre-logged trips must not affect
            # the current estimated tank level.
            if _event_date > today:
                break

            if event_type == 'fill':
                tank_level, has_fill = FuelForecastingService._apply_fill(
                    tank_level, tank_capacity, event_obj, has_fill
                )
                miles_since_fill = 0  # reset on every fill

            elif event_type == 'trip' and has_fill:
                gallons_used = event_obj.total_miles / avg_mpg
                tank_level = max(0.0, tank_level - gallons_used)
                miles_since_fill += event_obj.total_miles

        if not has_fill:
            return None

        gallons_remaining = tank_level
        gallons_consumed = miles_since_fill / avg_mpg  # for display only
        tank_pct = min(100.0, (gallons_remaining / tank_capacity) * 100)
        estimated_range = int(gallons_remaining * avg_mpg)

        # Miles the vehicle can drive before hitting the low-fuel threshold
        gallons_until_threshold = max(0.0, gallons_remaining - low_threshold)
        miles_to_refill = int(gallons_until_threshold * avg_mpg)

        # Average daily miles over the past 30 days (actual trips only)
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
            'last_fill_is_partial': bool(last_fill.is_partial_fill) if last_fill else False,
            'miles_since_fill': miles_since_fill,
            'gallons_consumed': round(gallons_consumed, 2),
            'gallons_remaining': round(gallons_remaining, 2),
            'tank_pct': round(tank_pct, 1),
            'estimated_range_miles': estimated_range,
            'miles_to_refill': miles_to_refill,
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
        Tracking begins from the first actual fill.  Predicted future refills are
        injected so the displayed tank column does not drain past each forecast date.

        Returns dict {trip_id: tank_pct}.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return {}

        tank_capacity = float(vehicle.tank_size)
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return {}

        all_fills = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .order_by(FuelRecord.date.asc())
            .all()
        )
        all_trips = (
            family_query(Trip)
            .filter_by(vehicle_id=vehicle_id)
            .filter(Trip.total_miles > 0)
            .order_by(Trip.date.asc())
            .all()
        )

        predicted = FuelForecastingService.predict_refills(vehicle_id)

        events = FuelForecastingService._build_merged_timeline(all_trips, all_fills)
        for p in predicted:
            events.append((p['date'], 0, 'predicted_fill', p))
        # Sort key: 4-tuple (date, priority, id, sub_priority).
        # Actual fills (prio 0) always before trips (prio 1) on the same day.
        # Predicted fills that share a date with their trigger trip must land
        # between the preceding trip and the trigger trip, not before all trips.
        # We achieve this by giving them (date, 1, trigger_trip_id, -1), which
        # sorts after any trip whose id < trigger_trip_id and before the trigger.
        def _sort_key(x):
            event_date, prio, event_type, obj = x
            if event_type == 'predicted_fill':
                trigger_date = obj.get('trigger_trip_date')
                trigger_id = obj.get('trigger_trip_id', 0)
                if trigger_date and event_date == trigger_date:
                    # Same day as trigger trip: insert just before it.
                    return (event_date, 1, trigger_id, -1)
                # Earlier date: treat as a normal fill.
                return (event_date, 0, 0, 0)
            return (event_date, prio, getattr(obj, 'id', 0), 0)
        events.sort(key=_sort_key)

        has_fill = False
        tank_level = 0.0
        trip_tank_levels = {}

        for (event_date, _priority, event_type, event_obj) in events:
            if event_type == 'fill':
                tank_level, has_fill = FuelForecastingService._apply_fill(
                    tank_level, tank_capacity, event_obj, has_fill
                )
            elif event_type == 'predicted_fill' and has_fill:
                # Predicted refills always fill the tank to capacity
                tank_level = tank_capacity
            elif event_type == 'trip' and has_fill:
                gallons_used = event_obj.total_miles / avg_mpg
                tank_level = max(0.0, tank_level - gallons_used)
                trip_tank_levels[event_obj.id] = round((tank_level / tank_capacity) * 100, 1)

        return trip_tank_levels

    # ------------------------------------------------------------------ transactions

    @staticmethod
    def create_forecasted_transaction(vehicle_id, refill_date, cost, description=None):
        """Create (or update existing) forecasted transaction for a predicted refill."""
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return None

        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return None

        from models.vendors import Vendor
        from models.accounts import Account

        fuel_vendor = family_query(Vendor).filter_by(name='Fuel Station').first()

        account_id = vehicle.fuel_account_id
        if not account_id:
            current_account = family_query(Account).filter_by(name='Nationwide Current Account').first()
            account_id = current_account.id if current_account else None

        # Reuse an existing forecasted transaction for this date if one exists
        existing = (
            family_query(Transaction)
            .filter_by(transaction_date=refill_date, is_forecasted=True, category_id=fuel_category.id)
            .filter(Transaction.description.like(f'%{vehicle.registration}%'))
            .first()
        )

        if existing:
            existing.amount = -Decimal(str(cost))
            existing.vendor_id = fuel_vendor.id if fuel_vendor else existing.vendor_id
            existing.account_id = account_id
            return existing

        payday_period = PaydayService.get_period_for_date(refill_date)
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
            day_name=refill_date.strftime('%a'),
        )
        db.session.add(transaction)
        return transaction

    @staticmethod
    def sync_forecasted_transactions(vehicle_id):
        """
        Rebuild all forecasted fuel transactions for a vehicle.

        Deletes all existing forecasted transactions in the 'Transportation - Fuel'
        category matching the vehicle's registration, then calls predict_refills() and
        creates a forecasted transaction for every predicted date.

        Call this after adding/editing Trip or FuelRecord rows to keep forecasts current.

        Side effects: commits the session.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return

        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return

        family_query(Transaction).filter(
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id,
            Transaction.description.like(f'%{vehicle.registration}%'),
        ).delete(synchronize_session=False)

        for refill in FuelForecastingService.predict_refills(vehicle_id):
            FuelForecastingService.create_forecasted_transaction(
                vehicle_id=vehicle_id,
                refill_date=refill['date'],
                cost=refill['cost'],
            )

        db.session.commit()

    @staticmethod
    def link_fuel_record_to_transaction(fuel_record_id):
        """
        Convert a forecasted fuel transaction to actual when a real fill-up is recorded.

        Looks for a forecasted transaction within ±3 days of the fill date for the same
        vehicle registration.  If found, updates it to is_forecasted=False / is_paid=True
        with the actual amount and date.  If not found, creates a new actual transaction.

        In both cases, links the record via fuel_record.linked_transaction_id and calls
        sync_forecasted_transactions() to regenerate future forecasts.

        Returns the created or updated Transaction, or None if fuel record not found.

        Side effects: commits the session.
        """
        fuel_record = family_get(FuelRecord, fuel_record_id)
        if not fuel_record:
            return None

        vehicle = fuel_record.vehicle
        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return None

        from models.vendors import Vendor
        from models.accounts import Account

        fuel_vendor = family_query(Vendor).filter_by(name='Fuel Station').first()

        account_id = vehicle.fuel_account_id
        if not account_id:
            current_account = family_query(Account).filter_by(name='Nationwide Current Account').first()
            account_id = current_account.id if current_account else None

        # Find the nearest forecasted transaction (±3 days)
        forecasted = (
            family_query(Transaction)
            .filter(
                Transaction.transaction_date >= fuel_record.date - timedelta(days=3),
                Transaction.transaction_date <= fuel_record.date + timedelta(days=3),
                Transaction.is_forecasted == True,
                Transaction.category_id == fuel_category.id,
                Transaction.description.like(f'%{vehicle.registration}%'),
            )
            .first()
        )

        partial_label = ' (partial)' if fuel_record.is_partial_fill else ''

        if forecasted:
            forecasted.amount = -fuel_record.cost
            forecasted.transaction_date = fuel_record.date
            forecasted.is_forecasted = False
            forecasted.is_paid = True
            forecasted.description = f'Fuel{partial_label} - {vehicle.registration}'
            forecasted.item = f'{vehicle.name} - {fuel_record.gallons} gal @ £{fuel_record.cost}{partial_label}'
            forecasted.account_id = account_id
            forecasted.vendor_id = fuel_vendor.id if fuel_vendor else forecasted.vendor_id
            forecasted.year_month = fuel_record.date.strftime('%Y-%m')
            forecasted.day_name = fuel_record.date.strftime('%a')
            forecasted.payday_period = PaydayService.get_period_for_date(fuel_record.date)
            fuel_record.linked_transaction_id = forecasted.id
            transaction = forecasted
        else:
            payday_period = PaydayService.get_period_for_date(fuel_record.date)
            transaction = Transaction(
                account_id=account_id,
                category_id=fuel_category.id,
                vendor_id=fuel_vendor.id if fuel_vendor else None,
                amount=-fuel_record.cost,
                transaction_date=fuel_record.date,
                description=f'Fuel{partial_label} - {vehicle.registration}',
                item=f'{vehicle.name} - {fuel_record.gallons} gal @ £{fuel_record.cost}{partial_label}',
                is_forecasted=False,
                is_paid=True,
                payday_period=payday_period,
                year_month=fuel_record.date.strftime('%Y-%m'),
                day_name=fuel_record.date.strftime('%a'),
            )
            db.session.add(transaction)
            db.session.flush()
            fuel_record.linked_transaction_id = transaction.id

        db.session.commit()

        # Resync forecasted transactions now that a real fill has been recorded
        FuelForecastingService.sync_forecasted_transactions(vehicle.id)

        return transaction