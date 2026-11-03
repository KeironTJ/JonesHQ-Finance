"""Manage recurring journey schedules and their planned trip occurrences."""
from datetime import date, timedelta

from sqlalchemy import or_, update

from extensions import db
from models.family import Family
from models.trip_schedule import TripSchedule
from models.trips import Trip
from models.vehicles import Vehicle
from services.platform.site_settings_service import SiteSettingsService
from services.vehicles.vehicle_service import VehicleService
from utils import db_helpers
from utils.db_helpers import family_get_or_404, family_query


class TripRoutineLimitError(ValueError):
    """A routine exceeds the operator's generation limits."""


class TripScheduleService:
    """Create recurring trip plans while keeping planned and actual mileage distinct."""

    PLANNING_DAYS = 90

    @staticmethod
    def _lock_household():
        family_id = db_helpers.get_family_id()
        if family_id is None:
            raise ValueError('Sign in to manage trip routines.')
        # A write lock serializes quota checks on SQLite as well as PostgreSQL.
        result = db.session.execute(
            update(Family).where(Family.id == family_id).values(id=Family.id),
        )
        if result.rowcount != 1:
            raise ValueError('Household not found.')

    @staticmethod
    def active_routine_count(today=None):
        today = today or date.today()
        return family_query(TripSchedule, include_private=True).filter(
            TripSchedule.is_active.is_(True),
            or_(TripSchedule.end_date.is_(None), TripSchedule.end_date >= today),
        ).count()

    @staticmethod
    def _validate_dates(start_date, end_date, settings, today):
        latest = today + timedelta(days=settings.trip_planning_max_days)
        if start_date > latest or (end_date and end_date > latest):
            raise TripRoutineLimitError(
                f'Choose routine dates on or before {latest:%d %b %Y}. '
                f'Trips can be planned up to {settings.trip_planning_max_days:,} days ahead. '
                'Shorten the routine or ask the site administrator about the limit.'
            )

    @staticmethod
    def _validate_capacity(settings, *, adding=False, today=None):
        count = TripScheduleService.active_routine_count(today)
        if count + int(adding) > settings.trip_active_routine_limit:
            raise TripRoutineLimitError(
                f'Your household can have up to {settings.trip_active_routine_limit} active trip routines. '
                'Pause or end a routine before generating more trips or starting another.'
            )

    @staticmethod
    def _validated_data(data):
        vehicle_id = int(data['vehicle_id'])
        family_get_or_404(Vehicle, vehicle_id)

        name = (data.get('name') or '').strip()
        if not name:
            raise ValueError('Routine name is required')
        if len(name) > 100:
            raise ValueError('Routine name cannot exceed 100 characters')

        miles = int(data.get('miles') or 0)
        if miles < 0:
            raise ValueError('Miles cannot be negative')
        trip_type = data.get('trip_type', 'personal')
        if trip_type not in ('personal', 'business'):
            raise ValueError('Trip type must be personal or business')

        weekdays = {int(day) for day in data.getlist('days')}
        if not weekdays or any(day < 0 or day > 6 for day in weekdays):
            raise ValueError('Select at least one valid weekday')

        frequency = data.get('frequency', 'weekly')
        if frequency not in ('weekly', 'fortnightly'):
            raise ValueError('Frequency must be weekly or fortnightly')

        start_date = date.fromisoformat(data['start_date'])
        end_date = date.fromisoformat(data['end_date']) if data.get('end_date') else None
        if end_date and end_date < start_date:
            raise ValueError('End date must be on or after the start date')
        TripScheduleService._validate_dates(
            start_date, end_date, SiteSettingsService.get(), date.today(),
        )

        journey_description = (data.get('journey_description') or '').strip()
        if len(journey_description) > 255:
            raise ValueError('Journey description cannot exceed 255 characters')

        return {
            'vehicle_id': vehicle_id,
            'name': name,
            'trip_type': trip_type,
            'miles': miles,
            'journey_description': journey_description,
            'weekdays': ','.join(str(day) for day in sorted(weekdays)),
            'frequency': frequency,
            'start_date': start_date,
            'end_date': end_date,
        }

    @staticmethod
    def _occurrence_dates(schedule, today):
        start = max(today, schedule.start_date)
        end = schedule.end_date or (
            today + timedelta(days=min(
                TripScheduleService.PLANNING_DAYS - 1,
                SiteSettingsService.get().trip_planning_max_days,
            ))
        )
        if start > end:
            return []

        weekdays = {int(day) for day in schedule.weekdays.split(',')}
        interval = 2 if schedule.frequency == 'fortnightly' else 1
        start_of_schedule_week = schedule.start_date - timedelta(
            days=schedule.start_date.weekday(),
        )
        dates = []
        current = start
        while current <= end:
            start_of_current_week = current - timedelta(days=current.weekday())
            week_number = (start_of_current_week - start_of_schedule_week).days // 7
            if current.weekday() in weekdays and week_number % interval == 0:
                dates.append(current)
            current += timedelta(days=1)
        return dates

    @staticmethod
    def _trip_values(schedule, occurrence_date, latest_fuel):
        trip_cost, gallons_used, approx_mpg = VehicleService.calculate_trip_cost(
            schedule.vehicle_id, schedule.miles, occurrence_date,
        )
        return {
            'vehicle_id': schedule.vehicle_id,
            'scheduled_date': occurrence_date,
            'date': occurrence_date,
            'month': occurrence_date.strftime('%Y-%m'),
            'week': f'{occurrence_date.isocalendar()[1]:02d}-{occurrence_date.year}',
            'day_name': occurrence_date.strftime('%A'),
            'personal_miles': schedule.miles if schedule.trip_type == 'personal' else 0,
            'business_miles': schedule.miles if schedule.trip_type == 'business' else 0,
            'total_miles': schedule.miles,
            'journey_description': schedule.journey_description,
            'approx_mpg': approx_mpg,
            'gallons_used': gallons_used,
            'trip_cost': trip_cost,
            'fuel_cost': 0,
            'vehicle_last_fill': latest_fuel.date if latest_fuel else None,
        }

    @staticmethod
    def _materialize(schedules, today):
        settings = SiteSettingsService.get()
        TripScheduleService._validate_capacity(settings, today=today)
        for schedule in schedules:
            if schedule.is_active:
                TripScheduleService._validate_dates(
                    schedule.start_date, schedule.end_date, settings, today,
                )
        created_vehicle_ids = set()
        for schedule in schedules:
            if not schedule.is_active:
                continue
            occurrence_dates = TripScheduleService._occurrence_dates(schedule, today)
            if not occurrence_dates:
                continue

            existing_dates = {
                row[0]
                for row in family_query(Trip).filter(
                    Trip.schedule_id == schedule.id,
                    Trip.scheduled_date.in_(occurrence_dates),
                ).with_entities(Trip.scheduled_date).all()
            }
            latest_fuel = VehicleService.get_latest_fuel_record(schedule.vehicle_id)
            for occurrence_date in occurrence_dates:
                if occurrence_date in existing_dates:
                    continue
                db.session.add(Trip(
                    family_id=db_helpers.get_family_id(),
                    schedule_id=schedule.id,
                    trip_status='planned',
                    **TripScheduleService._trip_values(
                        schedule, occurrence_date, latest_fuel,
                    ),
                ))
                created_vehicle_ids.add(schedule.vehicle_id)
        return created_vehicle_ids

    @staticmethod
    def ensure_upcoming_trips(today=None):
        """Fill through each routine's end date, or 90 days ahead if open-ended."""
        TripScheduleService._lock_household()
        schedules = family_query(TripSchedule).filter_by(is_active=True).with_for_update().all()
        created_vehicle_ids = TripScheduleService._materialize(
            schedules, today or date.today(),
        )
        if created_vehicle_ids:
            db.session.commit()
        return created_vehicle_ids

    @staticmethod
    def create_schedule(data):
        TripScheduleService._lock_household()
        values = TripScheduleService._validated_data(data)
        if values['end_date'] is None or values['end_date'] >= date.today():
            TripScheduleService._validate_capacity(SiteSettingsService.get(), adding=True)
        schedule = TripSchedule(
            family_id=db_helpers.get_family_id(),
            **values,
        )
        db.session.add(schedule)
        db.session.flush()
        created_vehicle_ids = TripScheduleService._materialize([schedule], date.today())
        db.session.commit()
        return schedule, created_vehicle_ids

    @staticmethod
    def update_schedule(schedule_id, data):
        TripScheduleService._lock_household()
        schedule = family_get_or_404(TripSchedule, schedule_id)
        previous_vehicle_id = schedule.vehicle_id
        values = TripScheduleService._validated_data(data)
        if schedule.is_active:
            adding = (
                schedule.end_date is not None and schedule.end_date < date.today()
                and (values['end_date'] is None or values['end_date'] >= date.today())
            )
            TripScheduleService._validate_capacity(SiteSettingsService.get(), adding=adding)
        for field, value in values.items():
            setattr(schedule, field, value)
        today = date.today()
        occurrence_dates = set(TripScheduleService._occurrence_dates(schedule, today))
        future_skipped_trips = family_query(Trip).filter(
            Trip.schedule_id == schedule.id,
            Trip.trip_status == 'skipped',
            Trip.is_modified.is_(False),
            Trip.scheduled_date >= today,
        ).all()
        latest_fuel = VehicleService.get_latest_fuel_record(schedule.vehicle_id)
        for trip in future_skipped_trips:
            if trip.scheduled_date in occurrence_dates:
                for field, value in TripScheduleService._trip_values(
                    schedule, trip.scheduled_date, latest_fuel,
                ).items():
                    setattr(trip, field, value)
            else:
                db.session.delete(trip)
        # Occurrences edited for a single day keep their own details.
        family_query(Trip).filter(
            Trip.schedule_id == schedule.id,
            Trip.trip_status == 'planned',
            Trip.is_modified.is_(False),
            Trip.scheduled_date >= today,
        ).delete(synchronize_session='fetch')
        created_vehicle_ids = TripScheduleService._materialize([schedule], today)
        created_vehicle_ids.add(previous_vehicle_id)
        created_vehicle_ids.add(schedule.vehicle_id)
        db.session.commit()
        return schedule, created_vehicle_ids

    @staticmethod
    def set_schedule_active(schedule_id, is_active):
        TripScheduleService._lock_household()
        schedule = family_get_or_404(TripSchedule, schedule_id)
        if is_active:
            settings = SiteSettingsService.get()
            TripScheduleService._validate_dates(
                schedule.start_date, schedule.end_date, settings, date.today(),
            )
            adding = not schedule.is_active and (
                schedule.end_date is None or schedule.end_date >= date.today()
            )
            TripScheduleService._validate_capacity(settings, adding=adding)
        schedule.is_active = is_active
        today = date.today()
        if is_active:
            affected_vehicle_ids = TripScheduleService._materialize([schedule], today)
        else:
            family_query(Trip).filter(
                Trip.schedule_id == schedule.id,
                Trip.trip_status == 'planned',
                Trip.scheduled_date >= today,
            ).delete(synchronize_session='fetch')
            affected_vehicle_ids = {schedule.vehicle_id}
        db.session.commit()
        return affected_vehicle_ids

    CLEAR_ROUTINE_MODES = ('keep', 'skip', 'end')

    @staticmethod
    def clear_future_trips(from_date, vehicle_id=None, routine_mode='keep', today=None):
        """Remove trips dated on or after ``from_date``.

        Manual trips are deleted. Routine trips are left alone (``keep``), marked
        skipped while the routine carries on (``skip``), or removed with the routine
        ended the day before (``end``). Returns (summary dict, affected vehicle IDs).
        """
        today = today or date.today()
        if from_date <= today:
            raise ValueError('Choose a date after today')
        if routine_mode not in TripScheduleService.CLEAR_ROUTINE_MODES:
            raise ValueError('Choose what to do with routine trips')
        if vehicle_id is not None:
            family_get_or_404(Vehicle, vehicle_id)

        def scoped(query, model):
            return query.filter(model.vehicle_id == vehicle_id) if vehicle_id is not None else query

        vehicle_ids = set()
        summary = {'deleted': 0, 'skipped': 0, 'routines_ended': 0}
        for trip in scoped(family_query(Trip), Trip).filter(
            Trip.schedule_id.is_(None), Trip.date >= from_date,
        ).all():
            vehicle_ids.add(trip.vehicle_id)
            db.session.delete(trip)
            summary['deleted'] += 1

        if routine_mode == 'skip':
            for trip in scoped(family_query(Trip), Trip).filter(
                Trip.schedule_id.isnot(None),
                Trip.trip_status != 'skipped',
                Trip.date >= from_date,
            ).all():
                vehicle_ids.add(trip.vehicle_id)
                trip.trip_status = 'skipped'
                summary['skipped'] += 1
        elif routine_mode == 'end':
            schedules = scoped(family_query(TripSchedule), TripSchedule).filter(
                TripSchedule.is_active.is_(True),
                or_(TripSchedule.end_date.is_(None), TripSchedule.end_date >= from_date),
            ).all()
            for schedule in schedules:
                if schedule.start_date < from_date:
                    schedule.end_date = from_date - timedelta(days=1)
                else:
                    schedule.is_active = False
                summary['routines_ended'] += 1
            for trip in family_query(Trip).filter(
                Trip.schedule_id.in_([schedule.id for schedule in schedules] or [-1]),
                Trip.date >= from_date,
            ).all():
                vehicle_ids.add(trip.vehicle_id)
                if trip.scheduled_date and trip.scheduled_date < from_date:
                    # Moved past the cut-off: keep the row so the date isn't regenerated.
                    trip.trip_status = 'skipped'
                    summary['skipped'] += 1
                else:
                    db.session.delete(trip)
                    summary['deleted'] += 1
            vehicle_ids.update(schedule.vehicle_id for schedule in schedules)

        db.session.flush()
        for affected_vehicle_id in vehicle_ids:
            VehicleService._recalculate_trip_cumulative_values(affected_vehicle_id)
        db.session.commit()
        return summary, vehicle_ids

    @staticmethod
    def delete_schedule(schedule_id):
        schedule = family_get_or_404(TripSchedule, schedule_id)
        vehicle_id = schedule.vehicle_id
        for trip in family_query(Trip).filter_by(schedule_id=schedule.id).all():
            if trip.trip_status == 'actual':
                trip.schedule_id = None
                trip.scheduled_date = None
            else:
                db.session.delete(trip)
        db.session.delete(schedule)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def set_occurrence_status(trip_id, status):
        trip = family_get_or_404(Trip, trip_id)
        vehicle_id = trip.vehicle_id
        if status == 'actual' and trip.trip_status == 'planned':
            trip.trip_status = 'actual'
        elif status == 'skipped' and trip.trip_status in ('planned', 'actual'):
            trip.trip_status = 'skipped'
        elif status == 'planned' and trip.trip_status == 'skipped':
            schedule = family_get_or_404(TripSchedule, trip.schedule_id) if trip.schedule_id else None
            if not schedule or not schedule.is_active:
                raise ValueError('This routine is no longer active')
            trip.trip_status = 'planned'
        else:
            raise ValueError('This trip cannot be changed to that status')
        VehicleService._recalculate_trip_cumulative_values(vehicle_id)
        db.session.commit()
        return vehicle_id

    @staticmethod
    def reset_occurrence(trip_id):
        """Discard single-day edits and restore the routine's details."""
        trip = family_get_or_404(Trip, trip_id)
        if not trip.schedule_id or trip.trip_status == 'actual':
            raise ValueError('Only planned or skipped routine trips can be reset')
        schedule = family_get_or_404(TripSchedule, trip.schedule_id)
        previous_vehicle_id = trip.vehicle_id
        for field, value in TripScheduleService._trip_values(
            schedule,
            trip.scheduled_date,
            VehicleService.get_latest_fuel_record(schedule.vehicle_id),
        ).items():
            setattr(trip, field, value)
        trip.school_holidays = None
        trip.is_modified = False
        db.session.commit()
        return {previous_vehicle_id, trip.vehicle_id}

    @staticmethod
    def get_overview(today=None):
        """Summarise each routine for the management page."""
        today = today or date.today()
        settings = SiteSettingsService.get()
        capacity_warning = None
        try:
            TripScheduleService._validate_capacity(settings, today=today)
        except ValueError as error:
            capacity_warning = str(error)
        schedules = family_query(TripSchedule).order_by(
            TripSchedule.is_active.desc(), TripSchedule.name,
        ).all()
        trips_by_schedule = {}
        if schedules:
            for trip in family_query(Trip).filter(
                Trip.schedule_id.in_([schedule.id for schedule in schedules]),
            ).all():
                trips_by_schedule.setdefault(trip.schedule_id, []).append(trip)

        overview = []
        for schedule in schedules:
            limit_warning = None
            if schedule.is_active and (schedule.end_date is None or schedule.end_date >= today):
                limit_warning = capacity_warning
                try:
                    TripScheduleService._validate_dates(
                        schedule.start_date, schedule.end_date, settings, today,
                    )
                except ValueError as error:
                    limit_warning = str(error)
            trips = trips_by_schedule.get(schedule.id, [])
            upcoming = sorted(
                (trip for trip in trips if trip.trip_status == 'planned' and trip.date > today),
                key=lambda trip: trip.date,
            )
            completed = [trip for trip in trips if trip.trip_status == 'actual']
            overview.append({
                'schedule': schedule,
                'limit_warning': limit_warning,
                'next_trip': upcoming[0] if upcoming else None,
                'upcoming_count': len(upcoming),
                'due_count': sum(
                    1 for trip in trips
                    if trip.trip_status == 'planned' and trip.date <= today
                ),
                'skipped_count': sum(
                    1 for trip in trips
                    if trip.trip_status == 'skipped' and trip.date >= today
                ),
                'modified_count': sum(
                    1 for trip in trips
                    if trip.is_modified and trip.trip_status != 'actual' and trip.date >= today
                ),
                'last_completed': max((trip.date for trip in completed), default=None),
            })
        return overview

    @staticmethod
    def get_occurrences(schedule_id, today=None, history_days=60):
        """Return a routine's recent history and upcoming trips in date order."""
        today = today or date.today()
        schedule = family_get_or_404(TripSchedule, schedule_id)
        trips = family_query(Trip).filter(
            Trip.schedule_id == schedule.id,
            Trip.date >= today - timedelta(days=history_days),
        ).order_by(Trip.date, Trip.id).all()
        return schedule, trips
