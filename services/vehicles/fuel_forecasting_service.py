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
   to or below the refuel threshold, predict a top-up BEFORE the current trip,
   dated on that trip's day. Trips longer than one tank's usable range include
   additional same-day top-ups at the threshold.
5. Only simulate predicted fills after the latest actual fill. Earlier trips and
   fills establish the actual tank level; unrecorded fills never seed a partial fill.

The threshold is expressed as a percentage of the tank already consumed:
  refuel_threshold_pct = 95  â†’ predict a fill when only 5 % of the tank remains.
  low_threshold_gallons = tank_capacity Ã— (1 âˆ’ refuel_threshold_pct / 100)

Forecasted transactions
-----------------------
``sync_forecasted_transactions()`` deletes all forecasted fuel transactions for
the vehicle and recreates them from the latest predictions.  When a real FuelRecord is
logged, ``link_fuel_record_to_transaction()`` promotes the nearest forecasted transaction
to is_forecasted=False / is_paid=True (or creates a new actual transaction if none found).

Primary entry points
--------------------
  predict_refills()                   â€” list of predicted refill dates + costs
  sync_forecasted_transactions()      â€” delete stale forecasts and recreate from predictions
  link_fuel_record_to_transaction()   â€” convert a forecasted transaction to actual on fill
"""
from datetime import date as date_type, timedelta
from decimal import Decimal
from extensions import db
from models.vehicles import Vehicle
from models.fuel import FuelRecord
from models.trips import Trip
from models.transactions import Transaction
from models.categories import Category
from services.finance.payday_service import PaydayService
from utils.db_helpers import family_query, family_get


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
        """Average the latest completed full-to-full fuel-economy intervals."""
        from services.vehicles.vehicle_service import VehicleService

        samples = VehicleService.get_fuel_efficiency_samples(vehicle_id)[-recent_count:]
        if not samples:
            return None
        return float(round(sum(mpg for _fill, mpg in samples) / len(samples), 1))

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
        tank_level = Decimal(str(tank_level))
        tank_capacity = Decimal(str(tank_capacity))
        gallons_added = Decimal(str(fill_obj.gallons or 0))
        is_partial = bool(fill_obj.is_partial_fill)

        if not has_fill:
            # Anchor: first recorded fill
            new_level = min(tank_capacity, gallons_added) if is_partial else tank_capacity
            return new_level, True

        if is_partial:
            new_level = min(tank_capacity, tank_level + gallons_added)
        else:
            new_level = tank_capacity  # full fill always tops up to max
        return new_level, True

    @staticmethod
    def _simulate_trips(vehicle_id):
        """Return predictions and end-of-trip levels from one consistent timeline."""
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return [], {}

        tank_capacity = Decimal(str(vehicle.tank_size))
        threshold_pct = (
            Decimal(str(vehicle.refuel_threshold_pct))
            if vehicle.refuel_threshold_pct is not None else Decimal('95')
        )
        if tank_capacity <= 0:
            raise ValueError('Tank size must be greater than zero')
        if not 50 <= threshold_pct <= 100:
            raise ValueError('Refuel forecast threshold must be between 50 and 100 percent')
        low_threshold = tank_capacity * (1 - threshold_pct / 100)

        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        if not avg_mpg:
            return [], {}
        avg_mpg = Decimal(str(avg_mpg))
        avg_price = Decimal(str(FuelForecastingService.get_average_fuel_price(vehicle_id)))

        trips = (
            family_query(Trip)
            .filter_by(vehicle_id=vehicle_id)
            .filter(Trip.trip_status.in_(('actual', 'planned')))
            .all()
        )
        fuel_records = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .order_by(FuelRecord.date.asc(), FuelRecord.id.asc())
            .all()
        )
        latest_fill_id = fuel_records[-1].id if fuel_records else None
        events = FuelForecastingService._build_merged_timeline(trips, fuel_records)
        predicted_refills = []
        trip_tank_levels = {}
        tank_level = Decimal('0')
        has_fill = False
        forecasting = False

        def record_refill(trip):
            nonlocal tank_level
            fill_gallons = tank_capacity - tank_level
            cost = fill_gallons * Decimal('4.54609') * avg_price / 100
            predicted_refills.append({
                'date': trip.date,
                'gallons': float(round(fill_gallons, 2)),
                'cost': float(round(cost, 2)),
                'tank_level_before': float(round(tank_level, 2)),
                'trigger_trip_date': trip.date,
                'trigger_trip_id': trip.id,
            })
            tank_level = tank_capacity

        for (_event_date, _priority, event_type, event_obj) in events:
            if event_type == 'fill':
                tank_level, has_fill = FuelForecastingService._apply_fill(
                    tank_level, tank_capacity, event_obj, has_fill
                )
                forecasting = event_obj.id == latest_fill_id

            elif event_type == 'trip' and has_fill:
                gallons_needed = Decimal(event_obj.total_miles) / avg_mpg
                if forecasting:
                    if tank_level < tank_capacity and tank_level - gallons_needed <= low_threshold:
                        record_refill(event_obj)
                    # A full tank cannot cover a long trip: consume to the
                    # threshold and top up during the trip, never before it for £0.
                    while gallons_needed > tank_level - low_threshold:
                        gallons_needed -= tank_level - low_threshold
                        tank_level = low_threshold
                        record_refill(event_obj)
                tank_level = max(Decimal('0'), tank_level - gallons_needed)
                trip_tank_levels[event_obj.id] = float(round(tank_level / tank_capacity * 100, 1))

        return predicted_refills, trip_tank_levels

    # ------------------------------------------------------------------ public API

    @staticmethod
    def predict_refills(vehicle_id):
        """Predict same-day top-ups for trips reaching or crossing the threshold.

        Only trips after the latest actual fill receive predictions, including
        missed historical trips. Earlier history establishes an actual-only tank
        state. Full tanks are not topped up again before departure; long trips
        receive additional fills at the threshold during the journey.

        Returns dicts with date, gallons, cost, tank_level_before,
        trigger_trip_date and trigger_trip_id. Costs are in pounds.
        """
        return FuelForecastingService._simulate_trips(vehicle_id)[0]

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
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle or not vehicle.tank_size:
            return None

        tank_capacity = Decimal(str(vehicle.tank_size))
        low_threshold = tank_capacity * (1 - Decimal(str(vehicle.refuel_threshold_pct or 95)) / 100)
        avg_mpg = FuelForecastingService.get_average_mpg(vehicle_id)
        avg_price = FuelForecastingService.get_average_fuel_price(vehicle_id)

        if not avg_mpg:
            return None
        avg_mpg = Decimal(str(avg_mpg))

        all_fills = (
            family_query(FuelRecord)
            .filter_by(vehicle_id=vehicle_id)
            .filter(FuelRecord.date <= date_type.today())
            .order_by(FuelRecord.date.asc(), FuelRecord.id.asc())
            .all()
        )
        today = date_type.today()
        all_trips = (
            family_query(Trip)
            .filter_by(vehicle_id=vehicle_id)
            # Unconfirmed routine trips count until a fill confirms or a skip removes them.
            .filter(Trip.trip_status.in_(('actual', 'planned')))
            .filter(Trip.total_miles > 0)
            .order_by(Trip.date.asc())
            .all()
        )

        last_fill = all_fills[-1] if all_fills else None

        events = FuelForecastingService._build_merged_timeline(all_trips, all_fills)

        has_fill = False
        tank_level = Decimal('0')
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
                gallons_used = Decimal(event_obj.total_miles) / avg_mpg
                tank_level = max(Decimal('0'), tank_level - gallons_used)
                miles_since_fill += event_obj.total_miles

        if not has_fill:
            return None

        gallons_remaining = tank_level
        gallons_consumed = Decimal(miles_since_fill) / avg_mpg  # for display only
        tank_pct = min(Decimal('100'), (gallons_remaining / tank_capacity) * 100)
        estimated_range = int(gallons_remaining * avg_mpg)

        # Miles the vehicle can drive before hitting the low-fuel threshold
        gallons_until_threshold = max(Decimal('0'), gallons_remaining - low_threshold)
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
        fill_litres = fill_gallons * Decimal('4.54609')
        estimated_fill_cost = float(round((fill_litres * Decimal(str(avg_price))) / 100, 2))

        return {
            'last_fill_date': last_fill.date if last_fill else None,
            'last_fill_gallons': float(last_fill.gallons) if last_fill and last_fill.gallons else None,
            'last_fill_is_partial': bool(last_fill.is_partial_fill) if last_fill else False,
            'miles_since_fill': miles_since_fill,
            'gallons_consumed': float(round(gallons_consumed, 2)),
            'gallons_remaining': float(round(gallons_remaining, 2)),
            'tank_pct': float(round(tank_pct, 1)),
            'estimated_range_miles': estimated_range,
            'miles_to_refill': miles_to_refill,
            'estimated_fill_date': estimated_fill_date,
            'days_until_refill': days_until_refill,
            'estimated_fill_cost': estimated_fill_cost,
            'tank_capacity': float(tank_capacity),
            'avg_mpg': float(avg_mpg),
        }

    @staticmethod
    def get_trip_tank_levels(vehicle_id):
        """
        Compute the estimated tank level (%) at the END of each trip.

        Uses the same simulation as predict_refills(), including top-ups before
        the triggering trip and additional fills during long trips. Older cycles
        use actual fills only.

        Returns dict {trip_id: tank_pct}.
        """
        return FuelForecastingService._simulate_trips(vehicle_id)[1]

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
            .filter(Transaction.description == (description or f'Forecasted fuel - {vehicle.registration}'))
            .first()
        )

        if existing:
            existing.amount = -Decimal(str(cost))
            existing.vendor_id = fuel_vendor.id if fuel_vendor else existing.vendor_id
            existing.account_id = account_id
            return existing

        payday_period = PaydayService.get_period_for_date(refill_date)
        transaction = Transaction(
            family_id=vehicle.family_id,
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
    def sync_forecasted_transactions(vehicle_id, previous_registration=None):
        """
        Rebuild all forecasted fuel transactions for a vehicle.

        Deletes all existing forecasted transactions in the 'Transportation - Fuel'
        category matching the vehicle's registration, then calls predict_refills() and
        creates one forecasted transaction per date, summing same-day fills.
        previous_registration clears stale forecasts when the registration changes.

        Call this after adding/editing Trip or FuelRecord rows to keep forecasts current.

        Side effects: commits the session.
        """
        vehicle = family_get(Vehicle, vehicle_id)
        if not vehicle:
            return

        fuel_category = family_query(Category).filter_by(name='Transportation - Fuel').first()
        if not fuel_category:
            return

        registrations = [vehicle.registration]
        if previous_registration and previous_registration != vehicle.registration:
            registrations.append(previous_registration)
        existing_query = family_query(Transaction).filter(
            Transaction.is_forecasted == True,
            Transaction.category_id == fuel_category.id,
            Transaction.description.in_([f'Forecasted fuel - {r}' for r in registrations]),
        )
        changes = {}
        for transaction in existing_query.all():
            if transaction.account_id:
                account_id = transaction.account_id
                changes[account_id] = min(
                    changes.get(account_id, transaction.transaction_date),
                    transaction.transaction_date,
                )

        daily_costs = {}
        for refill in FuelForecastingService.predict_refills(vehicle_id):
            day = refill['date']
            daily_costs[day] = daily_costs.get(day, Decimal('0')) + Decimal(str(refill['cost']))
        existing_query.delete(synchronize_session='fetch')

        for day, cost in daily_costs.items():
            transaction = FuelForecastingService.create_forecasted_transaction(
                vehicle_id=vehicle_id,
                refill_date=day,
                cost=cost,
            )
            if transaction and transaction.account_id:
                account_id = transaction.account_id
                changes[account_id] = min(changes.get(account_id, day), day)

        db.session.commit()
        from services.finance.monthly_balance_service import MonthlyBalanceService

        for account_id, day in changes.items():
            MonthlyBalanceService.handle_transaction_change(account_id, day)

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
                family_id=vehicle.family_id,
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