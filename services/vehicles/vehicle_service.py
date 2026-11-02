"""
Vehicle Service
===============
Fuel metrics, trip cost estimation, and bank-transaction creation for vehicle records.

Fuel metrics
------------
MPG is derived from completed full-to-full intervals, including all intervening
partial-fill gallons. Partial fills have no standalone MPG. Miles and purchase
cost per mile compare consecutive records. Fuel edits rebuild subsequent metrics.

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
from models.trip_template import TripTemplate
from models.transactions import Transaction
from models.categories import Category
from models.accounts import Account
from extensions import db
from datetime import datetime, date, timedelta
from decimal import Decimal
from sqlalchemy import func
from utils import db_helpers
from utils.db_helpers import family_query, family_get, family_get_or_404


class VehicleService:
    """
    Fuel efficiency metrics, trip cost estimation, and bank-transaction creation.

    All cost/price values use Decimal internally.  Prices are stored in pence-per-litre
    for fuel; costs and trip expenses are stored in pounds.
    """

    @staticmethod
    def _get_fuel_account_id(data):
        account_id = int(data['fuel_account_id']) if data.get('fuel_account_id') else None
        if account_id is not None and not family_get(Account, account_id):
            raise ValueError('Invalid fuel account selected')
        return account_id

    @staticmethod
    def _validate_fuel_settings(data):
        if data.get('tank_size') and Decimal(data['tank_size']) <= 0:
            raise ValueError('Tank size must be greater than zero')
        if data.get('refuel_threshold_pct') and not 50 <= Decimal(data['refuel_threshold_pct']) <= 100:
            raise ValueError('Refuel forecast threshold must be between 50 and 100 percent')

    @staticmethod
    def create_vehicle(data):
        fuel_account_id = VehicleService._get_fuel_account_id(data)
        VehicleService._validate_fuel_settings(data)
        vehicle = Vehicle(
            family_id=db_helpers.get_family_id(),
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
            fuel_account_id=fuel_account_id,
            refuel_threshold_pct=Decimal(
                data.get('refuel_threshold_pct') or '95'
            ),
            owner_id=(
                db_helpers.get_current_user_id() if data.get('visibility') == 'private' else None
            ),
            is_active=True,
        )
        db.session.add(vehicle)
        db.session.commit()
        return vehicle

    @staticmethod
    def update_vehicle(vehicle_id, data):
        vehicle = family_get_or_404(Vehicle, vehicle_id)
        fuel_account_id = VehicleService._get_fuel_account_id(data)
        VehicleService._validate_fuel_settings(data)
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
        vehicle.fuel_account_id = fuel_account_id
        vehicle.owner_id = (
            db_helpers.get_current_user_id() if data.get('visibility') == 'private' else None
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
        family_get_or_404(Vehicle, vehicle_id)
        fuel_record = FuelRecord(
            family_id=db_helpers.get_family_id(),
            vehicle_id=vehicle_id,
            date=fuel_date,
            price_per_litre=price_per_litre,
            mileage=mileage,
            cost=cost,
            gallons=gallons,
            is_partial_fill=data.get('is_partial_fill') == '1',
        )
        db.session.add(fuel_record)
        db.session.flush()
        VehicleService._recalculate_fuel_metrics(vehicle_id)
        fuel_record.confirmed_trip_count = len(VehicleService._confirm_planned_trips(
            fuel_date, vehicle_id,
        ))
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
        VehicleService._recalculate_fuel_metrics(fuel_record.vehicle_id)
        fuel_record.confirmed_trip_count = len(VehicleService._confirm_planned_trips(
            fuel_record.date, fuel_record.vehicle_id,
        ))
        db.session.commit()
        return fuel_record

    @staticmethod
    def delete_fuel_record(fuel_id):
        fuel_record = family_get_or_404(FuelRecord, fuel_id)
        vehicle_id = fuel_record.vehicle_id
        db.session.delete(fuel_record)
        db.session.flush()
        VehicleService._recalculate_fuel_metrics(vehicle_id)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def create_trip(data):
        vehicle_id = int(data['vehicle_id'])
        family_get_or_404(Vehicle, vehicle_id)
        trip_date = date.fromisoformat(data['date'])
        trip_type = data.get('trip_type', 'personal')
        miles = int(data.get('miles') or 0)
        if miles < 0:
            raise ValueError('Miles cannot be negative')
        if trip_type not in ('personal', 'business'):
            raise ValueError('Trip type must be personal or business')
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
            vehicle_id, miles, trip_date
        )
        latest_fuel = VehicleService.get_latest_fuel_record(vehicle_id)
        trip = Trip(
            family_id=db_helpers.get_family_id(),
            vehicle_id=vehicle_id,
            date=trip_date,
            month=trip_date.strftime('%Y-%m'),
            week=f'{trip_date.isocalendar()[1]:02d}-{trip_date.year}',
            day_name=trip_date.strftime('%A'),
            personal_miles=miles if trip_type == 'personal' else 0,
            business_miles=miles if trip_type == 'business' else 0,
            total_miles=miles,
            journey_description=data.get('journey_description', ''),
            school_holidays=data.get('school_holidays', ''),
            approx_mpg=approx_mpg,
            gallons_used=gallons_used,
            trip_cost=trip_cost,
            fuel_cost=Decimal('0'),
            vehicle_last_fill=latest_fuel.date if latest_fuel else None,
        )
        db.session.add(trip)
        db.session.flush()
        VehicleService._recalculate_trip_cumulative_values(vehicle_id)
        db.session.commit()
        return trip

    @staticmethod
    def update_trip(trip_id, data):
        trip = family_get_or_404(Trip, trip_id)
        previous_vehicle_id = trip.vehicle_id
        if data.get('vehicle_id'):
            trip.vehicle_id = family_get_or_404(Vehicle, int(data['vehicle_id'])).id
        trip.date = date.fromisoformat(data['date'])
        trip.month = trip.date.strftime('%Y-%m')
        trip.week = f'{trip.date.isocalendar()[1]:02d}-{trip.date.year}'
        trip.day_name = trip.date.strftime('%A')
        trip_type = data.get('trip_type', 'personal')
        miles = int(data.get('miles') or 0)
        if miles < 0:
            raise ValueError('Miles cannot be negative')
        if trip_type not in ('personal', 'business'):
            raise ValueError('Trip type must be personal or business')
        trip.personal_miles = miles if trip_type == 'personal' else 0
        trip.business_miles = miles if trip_type == 'business' else 0
        trip.total_miles = miles
        if trip.schedule_id:
            trip.is_modified = True
        trip.journey_description = data.get('journey_description', '')
        trip.school_holidays = data.get('school_holidays', '')
        trip.trip_cost, trip.gallons_used, trip.approx_mpg = VehicleService.calculate_trip_cost(
            trip.vehicle_id, miles, trip.date
        )
        VehicleService._recalculate_trip_cumulative_values(trip.vehicle_id)
        if previous_vehicle_id != trip.vehicle_id:
            VehicleService._recalculate_trip_cumulative_values(previous_vehicle_id)
        trip.previous_vehicle_id = previous_vehicle_id
        db.session.commit()
        return trip

    @staticmethod
    def _confirm_planned_trips(through_date, vehicle_id=None):
        """Mark planned trips on or before ``through_date`` as completed."""
        query = family_query(Trip).filter(
            Trip.trip_status == 'planned',
            Trip.date <= through_date,
        )
        if vehicle_id is not None:
            query = query.filter(Trip.vehicle_id == vehicle_id)
        trips = query.all()
        for trip in trips:
            trip.trip_status = 'actual'
        db.session.flush()
        for affected_vehicle_id in {trip.vehicle_id for trip in trips}:
            VehicleService._recalculate_trip_cumulative_values(affected_vehicle_id)
        return trips

    @staticmethod
    def confirm_due_trips(vehicle_id=None, today=None):
        """Confirm every planned trip dated today or earlier; return (count, vehicle IDs)."""
        if vehicle_id is not None:
            family_get_or_404(Vehicle, vehicle_id)
        trips = VehicleService._confirm_planned_trips(today or date.today(), vehicle_id)
        db.session.commit()
        return len(trips), {trip.vehicle_id for trip in trips}

    @staticmethod
    def _recalculate_trip_cumulative_values(vehicle_id):
        cumulative_miles = 0
        cumulative_gallons = Decimal('0')
        trips = family_query(Trip).filter(
            Trip.vehicle_id == vehicle_id,
            Trip.trip_status == 'actual',
        ).order_by(Trip.date, Trip.id).all()
        for trip in trips:
            cumulative_miles += trip.total_miles or 0
            cumulative_gallons += trip.gallons_used or Decimal('0')
            trip.cumulative_total_miles = cumulative_miles
            trip.cumulative_gallons = cumulative_gallons

    @staticmethod
    def delete_trip(trip_id):
        trip = family_get_or_404(Trip, trip_id)
        vehicle_id = trip.vehicle_id
        if trip.schedule_id:
            trip.trip_status = 'skipped'
        else:
            db.session.delete(trip)
        db.session.flush()
        VehicleService._recalculate_trip_cumulative_values(vehicle_id)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def bulk_create_trips(data):
        vehicle_id = int(data['vehicle_id'])
        family_get_or_404(Vehicle, vehicle_id)
        start_date = date.fromisoformat(data['start_date'])
        end_date = date.fromisoformat(data['end_date'])
        if start_date > end_date:
            raise ValueError('Start date must be before or equal to end date')
        if (end_date - start_date).days > 365:
            raise ValueError('Date range cannot be longer than 366 days')
        selected_days = {int(day) for day in data.getlist('days')}
        if any(day < 0 or day > 6 for day in selected_days):
            raise ValueError('Selected days are invalid')
        if not selected_days:
            raise ValueError('At least one day must be selected')

        miles_int = int(data.get('miles') or 0)
        if miles_int < 0:
            raise ValueError('Miles cannot be negative')
        miles = Decimal(miles_int)
        trip_type = data.get('trip_type', 'personal')
        if trip_type not in ('personal', 'business'):
            raise ValueError('Trip type must be personal or business')
        latest_fuel = VehicleService.get_latest_fuel_record(vehicle_id)
        created = []
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() in selected_days:
                trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
                    vehicle_id, miles, current_date
                )
                trip = Trip(
                    family_id=db_helpers.get_family_id(),
                    vehicle_id=vehicle_id,
                    date=current_date,
                    month=current_date.strftime('%Y-%m'),
                    week=f'{current_date.isocalendar()[1]:02d}-{current_date.year}',
                    day_name=current_date.strftime('%A'),
                    personal_miles=miles_int if trip_type == 'personal' else 0,
                    business_miles=miles_int if trip_type == 'business' else 0,
                    total_miles=miles_int,
                    journey_description=data.get('journey_description', ''),
                    school_holidays=data.get('school_holidays', ''),
                    approx_mpg=approx_mpg,
                    gallons_used=gallons_used,
                    trip_cost=trip_cost,
                    fuel_cost=Decimal('0'),
                    vehicle_last_fill=latest_fuel.date if latest_fuel else None,
                )
                db.session.add(trip)
                created.append(trip)
            current_date += timedelta(days=1)
        db.session.flush()
        VehicleService._recalculate_trip_cumulative_values(vehicle_id)
        db.session.commit()
        return created

    @staticmethod
    def _validated_trip_template_data(data):
        vehicle_id = int(data['vehicle_id'])
        family_get_or_404(Vehicle, vehicle_id)
        name = (data.get('name') or '').strip()
        if not name:
            raise ValueError('Journey name is required')
        miles = int(data.get('miles') or 0)
        if miles < 0:
            raise ValueError('Miles cannot be negative')
        trip_type = data.get('trip_type', 'personal')
        if trip_type not in ('personal', 'business'):
            raise ValueError('Trip type must be personal or business')
        return {
            'vehicle_id': vehicle_id,
            'name': name,
            'trip_type': trip_type,
            'miles': miles,
            'journey_description': (data.get('journey_description') or '').strip(),
        }

    @staticmethod
    def create_trip_template(data):
        template_data = VehicleService._validated_trip_template_data(data)
        template = TripTemplate(
            family_id=db_helpers.get_family_id(),
            **template_data,
        )
        db.session.add(template)
        db.session.commit()
        return template

    @staticmethod
    def update_trip_template(template_id, data):
        template = family_get_or_404(TripTemplate, template_id)
        template_data = VehicleService._validated_trip_template_data(data)
        for field, value in template_data.items():
            setattr(template, field, value)
        db.session.commit()
        return template

    @staticmethod
    def delete_trip_template(template_id):
        template = family_get_or_404(TripTemplate, template_id)
        db.session.delete(template)
        db.session.commit()

    @staticmethod
    def _metrics_for_fills(fills):
        """Yield each chronological fill and its derived metrics."""
        previous_fill = None
        full_anchor = None
        interval_gallons = Decimal('0')
        cumulative_miles = 0
        for fill in fills:
            actual_miles = fill.mileage - previous_fill.mileage if previous_fill else 0
            cumulative_miles += actual_miles
            price_per_mile = Decimal(str(fill.cost)) / Decimal(actual_miles) if actual_miles > 0 else Decimal('0')
            mpg = Decimal('0')
            if full_anchor is not None:
                interval_gallons += Decimal(str(fill.gallons))
                interval_miles = fill.mileage - full_anchor.mileage
                if not fill.is_partial_fill and interval_gallons > 0 and interval_miles > 0:
                    mpg = Decimal(interval_miles) / interval_gallons
            if not fill.is_partial_fill:
                full_anchor = fill
                interval_gallons = Decimal('0')
            yield fill, (
                actual_miles, mpg, price_per_mile,
                previous_fill.date if previous_fill else None, cumulative_miles,
            )
            previous_fill = fill

    @staticmethod
    def _recalculate_fuel_metrics(vehicle_id):
        fills = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(
            FuelRecord.date.asc(), FuelRecord.id.asc(),
        ).all()
        for fill, metrics in VehicleService._metrics_for_fills(fills):
            (
                fill.actual_miles, fill.mpg, fill.price_per_mile,
                fill.last_fill_date, fill.actual_cumulative_miles,
            ) = metrics

    @staticmethod
    def get_fuel_efficiency_samples(vehicle_id, end_date=None):
        """Return (full fill, MPG) samples without trusting legacy stored MPG."""
        query = family_query(FuelRecord).filter_by(vehicle_id=vehicle_id)
        if end_date is not None:
            query = query.filter(FuelRecord.date <= end_date)
        fills = query.order_by(FuelRecord.date.asc(), FuelRecord.id.asc()).all()
        return [
            (fill, metrics[1])
            for fill, metrics in VehicleService._metrics_for_fills(fills)
            if metrics[1] > 0
        ]

    @staticmethod
    def get_fuel_mpg_for_records(records):
        """Return derived MPG for displayed records, excluding partial intervals."""
        record_ids = {fill.id for fill in records}
        return {
            fill.id: mpg
            for vehicle_id in {fill.vehicle_id for fill in records}
            for fill, mpg in VehicleService.get_fuel_efficiency_samples(vehicle_id)
            if fill.id in record_ids
        }

    @staticmethod
    def calculate_fuel_metrics(vehicle_id, current_mileage, gallons, cost, fuel_date):
        """Calculate metrics for a proposed full fill after earlier dated records."""
        fills = family_query(FuelRecord).filter(
            FuelRecord.vehicle_id == vehicle_id, FuelRecord.date < fuel_date,
        ).order_by(FuelRecord.date.asc(), FuelRecord.id.asc()).all()
        fills.append(FuelRecord(
            date=fuel_date, mileage=current_mileage, gallons=gallons,
            cost=cost, is_partial_fill=False,
        ))
        return list(VehicleService._metrics_for_fills(fills))[-1][1]
    
    @staticmethod
    def get_latest_fuel_record(vehicle_id):
        """Get the most recent fuel record for a vehicle"""
        return family_query(FuelRecord).filter_by(vehicle_id=vehicle_id).order_by(FuelRecord.date.desc()).first()
    
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
        
        mpg_records = [mpg for _fill, mpg in VehicleService.get_fuel_efficiency_samples(vehicle_id)]
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
        recent_samples = VehicleService.get_fuel_efficiency_samples(vehicle_id, trip_date)[-10:]
        
        if not recent_samples:
            all_samples = VehicleService.get_fuel_efficiency_samples(vehicle_id)
            if not all_samples:
                return Decimal('0'), Decimal('0'), Decimal('0')
            latest_fuel, avg_mpg = all_samples[-1]
            price_per_gallon = (
                Decimal(str(latest_fuel.cost)) / Decimal(str(latest_fuel.gallons))
                if latest_fuel.gallons > 0 else Decimal('0')
            )
        else:
            avg_mpg = sum(mpg for _fill, mpg in recent_samples) / Decimal(len(recent_samples))
            
            # Get average price per gallon from recent fills (last 3)
            recent_price_records = [fill for fill, _mpg in recent_samples[-3:]]
            avg_price_per_gallon = sum([
                Decimal(str(f.cost)) / Decimal(str(f.gallons)) if f.gallons > 0 else Decimal('0')
                for f in recent_price_records
            ]) / Decimal(len(recent_price_records))
            price_per_gallon = avg_price_per_gallon
        
        gallons_used = Decimal(miles) / avg_mpg if avg_mpg > 0 else Decimal('0')
        trip_cost = gallons_used * price_per_gallon
        
        return trip_cost, gallons_used, avg_mpg
    
    @staticmethod
    def create_fuel_transaction(fuel_record, account_id):
        """Create a transaction for a fuel purchase"""
        from services.finance.payday_service import PaydayService
        
        # Get or create Fuel category
        category = family_query(Category).filter(
            db.func.lower(Category.name) == 'fuel'
        ).first()
        
        if not category:
            category = Category(
                family_id=db_helpers.get_family_id(),
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
            family_id=db_helpers.get_family_id(),
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
